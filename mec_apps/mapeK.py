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
# Sinal de CPU consumido daqui é o MAX entre as instâncias VidProc
# (vide mec_app_inteligence.py:462 — `cpu_percentage = max(cpu_values)`).
# Com teto de CPU observado em ~20%, escolha de thresholds:
#   UP=10  → escala assim que UMA instância ultrapassa 50% do teto
#            (margem ampla pra reagir antes de saturar)
#   DOWN=5 → desescala quando TODAS estão claramente ociosas
#            (~25% do teto, evita oscilação no regime estacionário)
CPU_THRESHOLD_UP = 10
CPU_THRESHOLD_DOWN = 5
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


def initialize_state():
    """Sincroniza create_app['instance_numer'] com o MAIOR índice ativo + 1.

    Antes usávamos len(active), o que cria conflitos se houver buracos
    (ex: 0 e 2 vivos, mas 1 morreu → próximo índice deveria ser 3, não 2).
    Agora usamos `max(idx) + 1` pra garantir que SCALE_UP nunca colida com
    nome existente.
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
    try:
        response = requests.get(MONITOR_URL, timeout=5)
        response.raise_for_status()
        data = response.json()
        log(f"[DEBUG RESPONSE] {data}")
        cpu = data.get("current_avg_cpu_percent", None)

        try:
            cpu = float(cpu)
            log(f"[DEBUG RAW CPU] cpu={cpu} type={type(cpu)} source={MONITOR_URL}")
        except:
            log(f"⚠️ CPU inválida recebida: {cpu}")
            return None

        log(f"CPU atual: {cpu:.2f}%")
        return cpu

    except Exception as e:
        log(f"Erro ao coletar métricas: {e}")
        return None

# ================= ANALYZE =================
def analyze(cpu, instances):
    """Decide a ação. Não muta `last_action_time` aqui — só execute() faz isso
    em sucesso, pra que falhas de scale não disparem cooldown."""
    if cpu is None:
        return "NO_ACTION"

    # cooldown anti oscilação
    if time.time() - last_action_time < COOLDOWN_SEC:
        log("⏳ COOLDOWN ativo")
        return "NO_ACTION"

    log(f"""
[MAPE-K DEBUG]
cpu={cpu:.2f}
instances={instances}
threshold_up={CPU_THRESHOLD_UP}
threshold_down={CPU_THRESHOLD_DOWN}
""")

    if cpu > CPU_THRESHOLD_UP and instances < MAX_INSTANCES:
        log(f"AÇÃO: SCALE_UP (CPU {cpu:.2f} > {CPU_THRESHOLD_UP})")
        return "SCALE_UP"

    if cpu < CPU_THRESHOLD_DOWN and instances > MIN_INSTANCES:
        log(f"AÇÃO: SCALE_DOWN (CPU {cpu:.2f} < {CPU_THRESHOLD_DOWN})")
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
        num = create_app["instance_numer"] - 1

        if num < MIN_INSTANCES:
            return

        log(f"🧹 Removendo instância {num}")

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
                create_app["instance_numer"] -= 1
                last_action_time = time.time()
                log(f"✅ SCALE_DOWN concluído. instance_numer={create_app['instance_numer']}")
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
        action = analyze(cpu, create_app["instance_numer"])

        log(f"DECISÃO FINAL: {action}")

        execute(plan(action))

        log(f"Instâncias ativas: {create_app['instance_numer']}")
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