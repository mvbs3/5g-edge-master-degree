import time
import requests
import subprocess
import signal
import sys
import socket
import os
import numpy as np

# ================= CONFIG =================
CPU_THRESHOLD_UP = 15
CPU_THRESHOLD_DOWN = 10
MIN_INSTANCES = 2
MAX_INSTANCES = 10
METRICS_POLLING_INTERVAL = 5

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MEP_ADDRESS = os.getenv("MEP_ADDRESS", "172.22.0.162")
MONITOR_URL = f"http://{MEP_ADDRESS}/traffic_inteligence/cpu_percent"
DISCOVER_URL = f"http://{MEP_ADDRESS}/service_registry/v1/discover"
TARGET_APP_TYPE = os.getenv("TARGET_APP_TYPE", "VidProc")

create_app = {
    "instance_numer": 1,
    "port": 8090
}

processos_abertos = []

# cooldown anti-flapping
last_action_time = 0
COOLDOWN_SEC = 10

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

def run_background(cmd, cwd=None):
    processo = subprocess.Popen(
        cmd,
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=cwd,
    )
    processos_abertos.append(processo)
    return processo

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

def initialize_state():
    """Sincroniza create_app['instance_numer'] com o número real de instâncias VidProc."""
    active = discover_active_instances()
    n = max(len(active), 1)
    create_app["instance_numer"] = n
    log(f"🔁 Estado recuperado: {len(active)} instância(s) {TARGET_APP_TYPE} ativa(s). instance_numer={n}")
    return n

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
    global last_action_time

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
        last_action_time = time.time()
        log(f"AÇÃO: SCALE_UP (CPU {cpu:.2f} > {CPU_THRESHOLD_UP})")
        return "SCALE_UP"

    if cpu < CPU_THRESHOLD_DOWN and instances > MIN_INSTANCES:
        last_action_time = time.time()
        log(f"AÇÃO: SCALE_DOWN (CPU {cpu:.2f} < {CPU_THRESHOLD_DOWN})")
        return "SCALE_DOWN"

    return "NO_ACTION"

# ================= PLAN =================
def plan(action):
    return {"action": action}

# ================= EXECUTE =================
def execute(plan):
    action = plan["action"]

    if action == "SCALE_UP":
        num = create_app["instance_numer"]
        port = create_app["port"] + num
        host = get_local_ip()

        log(f"🚀 Subindo instância {num} na porta {port}")

        cmd = f"""
        python3 mec_instance_manager.py start mec_app1_instance{num} {port} examples/mec_app1.py \
        --mec_name VideoStreamingService{num} \
        --mec_host {host}
        """

        proc = run_background(cmd, cwd=PROJECT_ROOT)
        time.sleep(8)

        # Validação: o subprocess ainda está vivo? Se já saiu com erro, não
        # incrementamos o contador (evita drift).
        ret = proc.poll()
        if ret is not None and ret != 0:
            log(f"❌ SCALE_UP falhou (exit={ret}). Mantendo instance_numer em {num}.")
            return

        create_app["instance_numer"] += 1
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