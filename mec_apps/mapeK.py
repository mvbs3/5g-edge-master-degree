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

MEP_ADDRESS = os.getenv("MEP_ADDRESS", "172.22.0.162")
MONITOR_URL = f"http://{MEP_ADDRESS}/traffic_inteligence/cpu_percent"

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

def run_background(cmd):
    processo = subprocess.Popen(
        cmd,
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    processos_abertos.append(processo)

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

        run_background(cmd)

        create_app["instance_numer"] += 1
        time.sleep(8)

    elif action == "SCALE_DOWN":
        num = create_app["instance_numer"] - 1

        if num < MIN_INSTANCES:
            return

        log(f"🧹 Removendo instância {num}")

        try:
            requests.post(
                f"http://{MEP_ADDRESS}/traffic_inteligence/shut_down_mec_app",
                json={
                    "app_type": "VidProc",
                    "instance_name": f"VideoStreamingService{num}",
                    "container_name": f"mec_app1_instance{num}"
                },
                timeout=5
            )
            create_app["instance_numer"] -= 1

        except Exception as e:
            log(f"Erro ao remover: {e}")

# ================= LOOP =================
def run():
    create_app["instance_numer"] = 1

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