import time
import requests
import subprocess
import signal
import sys
import socket
import os
import re
import numpy as np

# ================= CONFIG =================
# Sinal de CPU: as duas decisões usam agregações DIFERENTES, de propósito.
#   UP   olha o MÁXIMO  → reage assim que UMA instância aquece (protege o SLA)
#   DOWN olha a MÉDIA   → desescala quando o POOL como um todo está ocioso
# Usar o máximo nos dois lados (como era antes) trava o pool no teto: com 100 UEs
# sempre existe uma instância acima de UP, e o máximo nunca cai abaixo de DOWN,
# então o número de instâncias só sobe — 2→10 e nunca mais desce.
# Com teto de CPU observado em ~20% por instância (--cpus=0.20):
#   UP=10   → uma instância passou de 50% do teto
#   DOWN=5  → o pool inteiro abaixo de 25% do teto
CPU_THRESHOLD_UP = float(os.getenv("CPU_THRESHOLD_UP", "10"))
CPU_THRESHOLD_DOWN = float(os.getenv("CPU_THRESHOLD_DOWN", "5"))
MIN_INSTANCES = 2
MAX_INSTANCES = 10
METRICS_POLLING_INTERVAL = 5

# Quanto esperar e quantas tentativas pra confirmar que uma SCALE_UP
# realmente registrou a instância no service_registry.
SCALE_UP_VERIFY_TIMEOUT_SEC = 30
SCALE_UP_VERIFY_INTERVAL_SEC = 3

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

MEP_ADDRESS = os.getenv("MEP_ADDRESS", "172.22.0.162")
MONITOR_URL = f"http://{MEP_ADDRESS}/traffic_inteligence/cpu_percent"
DISCOVER_URL = f"http://{MEP_ADDRESS}/service_registry/v1/discover"
TARGET_APP_TYPE = os.getenv("TARGET_APP_TYPE", "VidProc")
SERVICE_NAME_PATTERN = re.compile(r"^VideoStreamingService(\d+)$")

create_app = {
    "instance_numer": 1,
    "port": 8090
}
processos_abertos = []

# cooldown anti-flapping
last_action_time = 0
COOLDOWN_SEC = 30

# ================= LOG =================
def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

# ================= UTILS =================
def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 1))
        IP = s.getsockname()[0]
    except:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

def run_background(cmd, cwd=None, log_name="scale_up"):
    """Dispara processo em background, capturando stdout/stderr em arquivo
    pra que falhas do mec_instance_manager fiquem visíveis."""
    log_path = os.path.join(LOG_DIR, f"mapeK_{log_name}.log")
    log_file = open(log_path, "a")
    log_file.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} | {cmd.strip()} ===\n")
    log_file.flush()
    processo = subprocess.Popen(
        cmd,
        shell=True,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        cwd=cwd,
    )
    processos_abertos.append(processo)
    return processo, log_path

# ================= STATE RECOVERY =================
def discover_active_instances():
    """
    Consulta o MEP service registry para descobrir quantas instâncias do
    TARGET_APP_TYPE já estão ativas. Permite que o MAPE-K se reinicie sem
    desincronizar com a realidade (containers que continuam rodando).
    """
    try:
        response = requests.get(DISCOVER_URL, timeout=5)
        response.raise_for_status()
        services = response.json()

        active = [
            svc for svc in services
            if svc.get("type") == TARGET_APP_TYPE
        ]
        return active
    except Exception as e:
        log(f"⚠️ Falha ao descobrir instâncias ativas: {e}. Assumindo estado limpo.")
        return []


def _max_index_from_active(active):
    """Extrai o MAIOR índice numérico dos nomes 'VideoStreamingService<N>'.

    Retorna -1 se nenhum nome bater no padrão.
    """
    max_idx = -1
    for svc in active:
        name = svc.get("name", "")
        m = SERVICE_NAME_PATTERN.match(name)
        if m:
            idx = int(m.group(1))
            if idx > max_idx:
                max_idx = idx
    return max_idx


def live_indexes():
    """Índices das instâncias REALMENTE vivas, em ordem crescente.

    Fonte da verdade do loop: `instance_numer` só serve pra nomear a próxima
    instância e não cai quando um container morre sozinho, então contar por ele
    fazia o MAPE-K se achar no teto (e parar de crescer) ou tentar matar um
    índice que já estava morto.
    """
    indexes = []
    for svc in discover_active_instances():
        m = SERVICE_NAME_PATTERN.match(svc.get("name", ""))
        if m:
            indexes.append(int(m.group(1)))
    return sorted(indexes)


def initialize_state():
    """Define o próximo nome a usar: MAIOR índice ativo + 1.

    `instance_numer` é só o gerador de nomes — a contagem de instâncias vivas é
    lida do registry a cada ciclo (ver live_indexes()). O piso em MIN_INSTANCES
    existe porque o stack sobe as instâncias 0 e 1 no boot, então o próximo nome
    livre nunca deve ser menor que 2 mesmo que o registry ainda esteja vazio.
    """
    active = discover_active_instances()
    max_idx = _max_index_from_active(active)
    n = max(max_idx + 1, MIN_INSTANCES)
    create_app["instance_numer"] = n
    log(f"🔁 Estado recuperado: {len(active)} instância(s) {TARGET_APP_TYPE} ativa(s) "
        f"(maior índice={max_idx}). instance_numer={n}")
    return n


def verify_instance_registered(target_index, timeout_sec, interval_sec):
    """Aguarda a instância VideoStreamingService<target_index> aparecer
    no service_registry. Retorna True se aparecer dentro do timeout."""
    target_name = f"VideoStreamingService{target_index}"
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        active = discover_active_instances()
        names = {svc.get("name", "") for svc in active}
        if target_name in names:
            return True
        time.sleep(interval_sec)
    return False

# ================= MONITOR =================
def collect_metrics():
    """Devolve dict com o MÁXIMO, a MÉDIA e quantas instâncias reportaram CPU.

    O endpoint antigo só expunha `current_avg_cpu_percent` (que na verdade era o
    máximo); se o módulo de inteligência em execução for uma versão anterior, os
    campos novos não vêm e a média cai de volta pro máximo.
    """
    try:
        response = requests.get(MONITOR_URL, timeout=5)
        response.raise_for_status()
        data = response.json()
        log(f"[DEBUG RESPONSE] {data}")

        raw_max = data.get("cpu_max_percent", data.get("current_avg_cpu_percent"))
        raw_avg = data.get("cpu_avg_percent", raw_max)

        try:
            cpu_max = float(raw_max)
        except (TypeError, ValueError):
            log(f"⚠️ CPU inválida recebida: {raw_max}")
            return None

        try:
            cpu_avg = float(raw_avg)
        except (TypeError, ValueError):
            cpu_avg = cpu_max

        reported = data.get("active_instances")
        log(f"CPU atual: max={cpu_max:.2f}% avg={cpu_avg:.2f}% (instâncias reportando={reported})")
        return {"max": cpu_max, "avg": cpu_avg}

    except Exception as e:
        log(f"Erro ao coletar métricas: {e}")
        return None

# ================= ANALYZE =================
def analyze(cpu, instances):
    """Decide a ação. Não muta `last_action_time` aqui — só execute() faz isso
    em sucesso, pra que falhas de scale não disparem cooldown.

    `instances` é a contagem de instâncias VIVAS (vinda do registry), não o
    contador de nomes.
    """
    if cpu is None:
        return "NO_ACTION"

    # cooldown anti oscilação
    if time.time() - last_action_time < COOLDOWN_SEC:
        log("⏳ COOLDOWN ativo")
        return "NO_ACTION"

    log(f"""
[MAPE-K DEBUG]
cpu_max={cpu['max']:.2f}
cpu_avg={cpu['avg']:.2f}
instances={instances}
threshold_up={CPU_THRESHOLD_UP} (sobre o max)
threshold_down={CPU_THRESHOLD_DOWN} (sobre a media)
""")

    if cpu["max"] > CPU_THRESHOLD_UP and instances < MAX_INSTANCES:
        log(f"AÇÃO: SCALE_UP (max {cpu['max']:.2f} > {CPU_THRESHOLD_UP})")
        return "SCALE_UP"

    # Banda morta: só desescala se o pool estiver ocioso NA MÉDIA **e** nenhuma
    # instância estiver acima do gatilho de subida. Sem essa segunda condição,
    # "uma instância quente + pool ocioso" satisfaz UP e DOWN ao mesmo tempo e o
    # pool fica oscilando entre N e N-1 indefinidamente, inflando justamente a
    # métrica de estabilidade (scaling changes) que o experimento compara.
    if (
        cpu["avg"] < CPU_THRESHOLD_DOWN
        and cpu["max"] <= CPU_THRESHOLD_UP
        and instances > MIN_INSTANCES
    ):
        log(f"AÇÃO: SCALE_DOWN (avg {cpu['avg']:.2f} < {CPU_THRESHOLD_DOWN}, "
            f"max {cpu['max']:.2f} <= {CPU_THRESHOLD_UP})")
        return "SCALE_DOWN"

    return "NO_ACTION"

# ================= PLAN =================
def plan(action):
    return {"action": action}

# ================= EXECUTE =================
def execute(plan):
    """Executa a ação. Em SUCESSO atualiza last_action_time pra disparar
    cooldown; em FALHA não toca, pra permitir nova tentativa imediata."""
    global last_action_time
    action = plan["action"]

    if action == "SCALE_UP":
        num = create_app["instance_numer"]
        port = create_app["port"] + num
        host = get_local_ip()

        log(f"🚀 Subindo instância {num} na porta {port}")

        cmd = (
            f"python3 mec_instance_manager.py start mec_app1_instance{num} {port} "
            f"examples/mec_app1.py "
            f"--mec_name VideoStreamingService{num} "
            f"--mec_host {host}"
        )

        proc, log_path = run_background(cmd, cwd=PROJECT_ROOT, log_name=f"scale_up_{num}")

        # Validação dupla: (1) subprocess não falhou imediatamente, (2) instância
        # apareceu no service_registry dentro do timeout.
        time.sleep(8)
        ret = proc.poll()
        if ret is not None and ret != 0:
            log(f"❌ SCALE_UP subprocess saiu com exit={ret}. Veja {log_path}.")
            log(f"   instance_numer mantido em {num}.")
            return

        log(f"⏳ Verificando registro de VideoStreamingService{num} no service_registry...")
        if not verify_instance_registered(
            num, SCALE_UP_VERIFY_TIMEOUT_SEC, SCALE_UP_VERIFY_INTERVAL_SEC
        ):
            log(f"❌ SCALE_UP: instância NÃO apareceu no registry após "
                f"{SCALE_UP_VERIFY_TIMEOUT_SEC}s. Veja {log_path}.")
            log(f"   instance_numer mantido em {num}.")
            return

        create_app["instance_numer"] += 1
        last_action_time = time.time()
        log(f"✅ SCALE_UP concluído. instance_numer={create_app['instance_numer']}")

    elif action == "SCALE_DOWN":
        # Mata a instância viva de maior índice, e não `instance_numer - 1`: aquele
        # índice podia já estar morto, e o POST falhava ciclo após ciclo no mesmo
        # alvo, de modo que nenhuma instância era destruída dali em diante.
        alive = live_indexes()
        if len(alive) <= MIN_INSTANCES:
            log(f"🧹 SCALE_DOWN abortado: {len(alive)} instância(s) viva(s), mínimo é {MIN_INSTANCES}")
            return

        num = alive[-1]
        log(f"🧹 Removendo instância {num} (vivas: {alive})")

        try:
            response = requests.post(
                f"http://{MEP_ADDRESS}/traffic_inteligence/shut_down_mec_app",
                json={
                    "app_type": "VidProc",
                    "instance_name": f"VideoStreamingService{num}",
                    "container_name": f"mec_app1_instance{num}"
                },
                timeout=15
            )
            if response.status_code == 200:
                last_action_time = time.time()
                log(f"✅ SCALE_DOWN concluído: VideoStreamingService{num} removida")
            else:
                log(f"⚠️ shut_down_mec_app retornou {response.status_code}: {response.text[:200]}")

        except Exception as e:
            log(f"Erro ao remover: {e}")

# ================= LOOP =================
def run():
    initialize_state()

    while True:
        log("==== CICLO MAPE-K ====")

        cpu = collect_metrics()

        # A contagem vem do registry a cada ciclo: é o único jeito de perceber
        # instâncias que morreram sozinhas e de não travar o pool no teto.
        alive = live_indexes()
        instances = len(alive)
        if instances == 0:
            log("⚠️ Registry não retornou instâncias vivas; usando instance_numer como fallback")
            instances = create_app["instance_numer"]

        action = analyze(cpu, instances)

        log(f"DECISÃO FINAL: {action}")

        execute(plan(action))

        log(f"Instâncias ativas: {instances} (índices={alive}, próximo nome={create_app['instance_numer']})")
        time.sleep(METRICS_POLLING_INTERVAL)

# ================= EXIT =================
def signal_handler(sig, frame):
    log("Encerrando processos...")
    for p in processos_abertos:
        try:
            p.terminate()
        except:
            pass
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    log("MAPE-K iniciado")
    run()