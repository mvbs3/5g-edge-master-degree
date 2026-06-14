import subprocess
import time
import signal
import sys
import socket
import os
import re
import shutil
import requests
import random
from dataclasses import dataclass
from typing import List, Tuple, Optional
from enum import Enum

# Raiz do projeto — anchor pra todos os caminhos relativos. NÃO depende
# da cwd: usa o local físico deste script.
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = _PROJECT_ROOT  # alias retrocompatível

# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass
class AppConfig:
    """Central configuration for MEC applications."""
    container_name: str = "mec_app1_instance"
    base_port: int = 8090
    py_file: str = "examples/mec_app1.py"
    mec_name_template: str = "VideoStreamingService"
    mec_host_prefix: str = "10.0.0."
    initial_ip: int = 186

@dataclass
class StressTestConfig:
    """Configuration for stress testing scenarios."""
    cpu_threshold: int = 15
    consumer_wait_time: int = 10
    metrics_endpoint: str = "http://192.168.70.2/traffic_inteligence/cpu_percent"
    logs_dir: str = "stress_test_logs"

@dataclass
class DockerConfig:
    """Docker compose file configurations."""
    core_network: str = "sa-deploy.yaml"
    cm: str = "docker-compose-cm.yaml"
    mep: str = "docker-compose-mep.yaml"
    ran: str = "docker-compose-ran.yaml"
    ue: str = "docker-compose-nrue.yaml"
    prometheus_dir: str = "prometheus"
    docker_compose_dir: str = "docker-compose"

# Global configuration instances
app_config = AppConfig()
stress_config = StressTestConfig()
docker_config = DockerConfig()

# ============================================================================
# PROCESS MANAGEMENT
# ============================================================================

class ProcessManager:
    """Manages all running processes and terminals."""
    
    def __init__(self):
        self.open_processes: List[Tuple] = []
        self.open_receptors: List[Tuple] = []
        self.app_instance_counter: int = 0
    
    def add_process(self, process_obj, title: Optional[str] = None):
        """Register a new process."""
        self.open_processes.append((process_obj, title))
    
    def add_receptor(self, process_obj, title: Optional[str] = None):
        """Register a new receptor (consumer) process."""
        self.open_receptors.append((process_obj, title))
    
    def get_next_app_instance(self) -> Tuple[str, int]:
        """Get next MEC app instance name and port."""
        instance_num = self.app_instance_counter
        mec_name = f"{app_config.mec_name_template}{instance_num}"
        port = app_config.base_port + instance_num
        self.app_instance_counter += 1
        return mec_name, port, instance_num
    
    def close_all_processes(self):
        """Terminate all registered processes."""
        print("\nTerminating all open processes...")
        for process_obj, title in self.open_processes:
            self._terminate_process(process_obj, title)
    
    def close_all_receptors(self):
        """Terminate all receptor processes."""
        print("\nTerminating all receptor processes...")
        for process_obj, title in self.open_receptors:
            self._terminate_process(process_obj, title)
    
    @staticmethod
    def _terminate_process(process_obj, title: str = "Unknown"):
        """Helper to safely terminate a process."""
        try:
            if process_obj.poll() is None:
                print(f"Terminating process (PID: {process_obj.pid}, Title: '{title}')...")
                process_obj.terminate()
                process_obj.wait(timeout=5)
                if process_obj.poll() is None:
                    print(f"Force killing process (PID: {process_obj.pid})...")
                    process_obj.kill()
                    process_obj.wait(timeout=5)
            if process_obj.poll() is not None:
                print(f"✅ Process (PID: {process_obj.pid}) terminated.")
        except Exception as e:
            print(f"❌ Error terminating process (PID: {process_obj.pid}): {e}")

process_manager = ProcessManager()

# ============================================================================
# SYSTEM UTILITIES
# ============================================================================

def get_local_ip() -> str:
    """Get the local IP address of the machine."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

def update_env_files(ip: str):
    """Update .env files with MEC host IP."""
    env_paths = ['examples/.env', 'examples/app_testes/.env']
    try:
        for path in env_paths:
            with open(path, 'w') as f:
                f.write(f'MEC_HOST={ip}\n')
                f.write(f'')
        print(f"✅ .env files updated with MEC_HOST={ip}")
    except Exception as e:
        print(f"❌ Error updating .env files: {e}")

def kill_all_python_processes():
    """Kill all Python processes except the current script."""
    current_pid = os.getpid()
    try:
        cmd = f"ps -eo pid,comm | grep python | awk '{{if ($1 != {current_pid}) print $1}}' | xargs -r kill -9"
        subprocess.run(cmd, shell=True, check=True)
        print("✅ All Python processes (except current) terminated.")
    except Exception as e:
        print(f"⚠️ Error killing Python processes: {e}")

def kill_all_gnome_terminals():
    """Kill all GNOME terminals."""
    try:
        subprocess.run("pkill -f gnome-terminal", shell=True, check=True)
        print("✅ All GNOME terminals closed.")
    except Exception as e:
        print(f"⚠️ Error closing GNOME terminals: {e}")

# ============================================================================
# TERMINAL & PROCESS LAUNCHING
# ============================================================================

def open_terminal(
    command: str,
    directory: Optional[str] = None,
    visible: bool = True,
    minimize: bool = False,
    title: Optional[str] = None
) -> Tuple:
    """Open a terminal and execute a command."""
    # Resolve `directory` em relação à raiz do projeto (não da cwd atual).
    # Isso garante que `cd "{directory}"` funcione mesmo se o orchestrator
    # tiver sido lançado de fora do diretório do projeto.
    if directory:
        if not os.path.isabs(directory):
            directory = os.path.join(_PROJECT_ROOT, directory)
        full_command = f'cd "{directory}" && {command}'
    else:
        full_command = command

    # Salva logs em arquivo em vez de DEVNULL — caminho absoluto pra não
    # depender da cwd.
    logs_dir = os.path.join(_PROJECT_ROOT, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    log_file = os.path.join(logs_dir, f"{title or 'process'}.log")

    with open(log_file, "w") as f:
        process = subprocess.Popen(
            full_command,
            shell=True,
            stdout=f,
            stderr=subprocess.STDOUT
        )

    print(f"Background command executed (PID: {process.pid}) → {log_file}")
    return (process, title)

# ============================================================================
# DOCKER OPERATIONS
# ============================================================================

def start_docker_compose(compose_file: str, service_name: str = "", title: str = "", directory = docker_config.docker_compose_dir):
    """Start a Docker compose service."""
    cmd = f'docker-compose -f {compose_file} up'
    if service_name:
        cmd += f' {service_name}'
    open_terminal(cmd, directory=directory, title=title)

def start_prometheus_grafana():
    """Initialize Prometheus and Grafana."""
    local_ip = get_local_ip()
    print(f"Starting Prometheus and Grafana on {local_ip}...")
    try:
        cmd = (
            f'docker swarm init --advertise-addr {local_ip} && '
            f'sleep 2 && docker swarm join-token manager && '
            f'sleep 2 && HOSTNAME=$(hostname) docker stack deploy -c docker-stack.yml prom && '
            f'echo "Available at: http://{local_ip}:3000"'
        )
        subprocess.run(
            cmd,
            shell=True,
            check=True,
            cwd=docker_config.prometheus_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print(f"✅ Prometheus and Grafana ready at http://{local_ip}:3000")
        time.sleep(15)
    except Exception as e:
        print(f"❌ Error starting Prometheus/Grafana: {e}")

def stop_docker_containers():
    """Stop and remove all Docker containers."""
    try:
        subprocess.run('docker stop $(docker ps -q)', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run('docker rm $(docker ps -aq)', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("✅ Docker containers stopped and removed.")
    except Exception as e:
        print(f"⚠️ Error stopping containers: {e}")

def leave_docker_swarm():
    """Leave Docker swarm."""
    try:
        subprocess.run('docker swarm leave --force', shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("✅ Left Docker Swarm.")
    except Exception as e:
        print(f"⚠️ Error leaving swarm: {e}")

# ============================================================================
# MEC APPLICATION MANAGEMENT
# ============================================================================

def start_mec_apps(num_instances: int) -> List[str]:
    """Start multiple MEC app instances. Returns list of app names."""
    app_names = []
    for _ in range(num_instances):
        mec_name, port, instance_num = process_manager.get_next_app_instance()
        cmd = ( 
            f'python3 mec_instance_manager.py start '
            f'mec_app1_instance{instance_num} {port} {app_config.py_file} '
            f'--mec_name {mec_name} --mec_host {get_local_ip()}'
        )
        open_terminal(cmd, title=f"MEC_App_Instance_{instance_num}")
        app_names.append(mec_name)
        time.sleep(2)
    return app_names

def start_broadcaster(app_names: List[str], title: str = "Broadcaster"):
    """Start a broadcaster for the given apps."""
    cmd = f'source mec_app1/bin/activate && python3 app_testes/emissorBroadcast.py {" ".join(app_names)}'
    process_info = open_terminal(cmd, directory='examples', title=title)
    process_manager.add_process(process_info[0], process_info[1])
    time.sleep(5)

def start_receptor():
    """Start a single receptor (consumer) process."""
    consumer_id = len(process_manager.open_receptors) + 1
    title = f"Receptor_Consumer_{consumer_id}"
    cmd = 'source mec_app1/bin/activate && python3 app_testes/receptorV2Tester.py'
    process_info = open_terminal(cmd, directory='examples', title=title)
    process_manager.add_receptor(process_info[0], process_info[1])
    time.sleep(5)

def kill_last_receptor():
    """Kill the last active receptor process."""
    print("\nKilling last receptor...")
    try:
        cmd = "ps aux | grep receptorV2Tester.py | grep -v grep | tail -n 1 | awk '{print $2}'"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        pid = result.stdout.strip()
        
        if pid:
            subprocess.run(f"kill -9 {pid}", shell=True, check=True)
            print(f"✅ Killed receptor (PID: {pid})")
            if process_manager.open_receptors:
                process_manager.open_receptors.pop()
        else:
            print("No active receptor processes found.")
    except Exception as e:
        print(f"❌ Error killing receptor: {e}")

# ============================================================================
# CORE ENVIRONMENT SETUP
# ============================================================================
def start_mep_enviroment():
    print("\nStarting Docker_CM...")
    start_docker_compose(docker_config.cm, title="CM_Docker", directory="5g_mep")
    print("✅ Docker CM started.")
    time.sleep(10)
    
    print("\nStarting MEP Docker...")
    start_docker_compose(docker_config.mep, title="MEP_Docker", directory="5g_mep")
    print("✅ MEP started.")
    time.sleep(15)

def start_mep_inteligence_plus_catcher():
    

    print("\nStarting MEC Catcher APP...")
    open_terminal(
        'bash -c "source mec_app1/bin/activate && python3 mec_app_metric_catcher.py"',
        directory='mec_apps',
        title="Metric_Catcher"
    )
    print("✅ MEC Catcher started.")

    time.sleep(10)
    print("\nStarting MEC Intelligence APP...")
    open_terminal(
        'bash -c "source mec_app1/bin/activate && python3 mec_app_inteligence.py"',
        directory='mec_apps',
        title="MEC_Intelligence"
    )
    print("✅ MEC Intelligence APP started.")
    time.sleep(2)

def start_core_environment():
    """Start core network components (Core, CM, MEP, Intelligence, Catcher)."""
    print("\nStarting core environment...")
    
    start_docker_compose(docker_config.core_network, title="Core_Network_Docker", directory="5g_core")
    time.sleep(20)
    
    print("✅ Core environment started.")
def start_ran():
    print("\nStarting Ran environment...")
    start_docker_compose(docker_config.ran, title="Ran", directory="5g_ran")
    print("✅ Ran environment started.")
    time.sleep(10)
def start_ue():
    print("\nStarting nr_ue...")
    start_docker_compose(docker_config.ue, title="ue", directory="5g_ran")
    print("✅ nr_ue started.")
def start_ran_and_ue():
    """Start RAN and UE consumer."""
    print("\nStarting RAN and UE...")
    start_docker_compose(docker_config.ran, "oai-gnb oai-flexric rabbitmq", "RAN_Components")
    time.sleep(10)
    start_docker_compose(docker_config.ran, "oai-nr-ue", "OAI_NR_UE")
    time.sleep(3)
    print("✅ RAN and UE started.")

def start_mapeK():
    print("Starting MapeK...")
    open_terminal(
        'python3 mapeK.py',
        directory="mec_apps",
        title="mapeK"
    )
    print("✅ MapeK started.")
def start_mep_and_intelligence():
    """Start MEP, Intelligence, and Metric Catcher."""
    print("\nStarting MEP, Intelligence, and Catcher...")
    start_docker_compose(docker_config.mep, title="MEP_Docker")
    time.sleep(15)
    
    open_terminal(
        'source mec_app1/bin/activate && python3 mec_app_inteligence.py',
        directory='examples',
        title="MEC_Intelligence"
    )
    time.sleep(2)
    
    open_terminal(
        'source mec_app1/bin/activate && python3 mec_app_metric_catcher.py',
        directory='examples',
        title="Metric_Catcher"
    )
    time.sleep(5)
    print("✅ MEP, Intelligence, and Catcher started.")

# ============================================================================
# STRESS TESTING & MONITORING
# ============================================================================

def get_current_cpu_percent() -> Optional[float]:
    """Fetch current CPU usage from metrics endpoint."""
    try:
        response = requests.get(stress_config.metrics_endpoint, timeout=5)
        response.raise_for_status()
        metrics = response.json()
        return float(metrics.get("current_avg_cpu_percent", 0))
    except Exception as e:
        print(f"❌ Error fetching CPU metrics: {e}")
        return None

def run_stress_test_scenario(num_app_instances: int, initial_consumers: int = 0):
    """Run stress test with variable consumer count."""
    print(f"\n### Stress Test: {num_app_instances} App Instance(s) ###")
    
    if os.path.exists("stress_test_logs"):
        os.makedirs("stress_test_logs", exist_ok=True)
    
    if os.path.exists("examples/rl_input_state.csv"):
        os.remove("examples/rl_input_state.csv")
    
    start_prometheus_grafana()
    start_core_environment()
    
    app_names = start_mec_apps(num_app_instances)
    start_broadcaster(app_names, title=f"Broadcaster_{num_app_instances}_Instances")
    
    # Start initial consumers
    for _ in range(initial_consumers):
        start_receptor()
    
    current_consumers = initial_consumers
    
    while True:
        cpu_percent = get_current_cpu_percent()
        if cpu_percent is None or cpu_percent > stress_config.cpu_threshold:
            break
        
        print(f"CPU: {cpu_percent}% | Consumers: {current_consumers}")
        
        action = "CREATE" if current_consumers == 0 else random.choice(["CREATE", "DELETE"])
        
        if action == "CREATE":
            current_consumers += 1
            print(f"Creating consumer #{current_consumers}...")
            start_receptor()
        elif action == "DELETE" and current_consumers > 0:
            current_consumers -= 1
            print(f"Killing consumer (total now: {current_consumers})...")
            kill_last_receptor()
        
        time.sleep(stress_config.consumer_wait_time)
    
    print(f"✅ Test completed. Final consumer count: {current_consumers}")
    
    # Archive logs
    if os.path.exists("examples/mec_metrics.json"):
        os.rename(
            "examples/mec_metrics.json",
            f'stress_test_logs/metrics_{num_app_instances}inst_{current_consumers}cons.json'
        )
    if os.path.exists("examples/rl_input_state.csv"):
        os.rename(
            "examples/rl_input_state.csv",
            f'stress_test_logs/state_{num_app_instances}inst_{current_consumers}cons.csv'
        )

def cleanup_and_exit():
    """Clean up all resources and exit."""
    print("\n--- Shutting Down Environment ---")
    process_manager.close_all_processes()
    process_manager.close_all_receptors()
    stop_docker_containers()
    kill_all_python_processes()
    leave_docker_swarm()
    kill_all_gnome_terminals()
    print("\n--- Goodbye ---")
    sys.exit(0)

# ============================================================================
# AUTOMATED EXPERIMENT SUITE — Option 2
# ============================================================================


def kill_pattern(pattern: str):
    """Mata todos os processos cujo cmdline contém `pattern` (best-effort)."""
    try:
        subprocess.run(f"pkill -f '{pattern}'", shell=True, check=False)
    except Exception as e:
        print(f"⚠️ Erro matando '{pattern}': {e}")


def clean_experiment_csvs():
    """Remove CSVs do run anterior pra começar limpo."""
    paths = [
        os.path.join(PROJECT_ROOT, 'mec_apps/Results/rewards.csv'),
        os.path.join(PROJECT_ROOT, 'mec_apps/Results/arm_probabilities.csv'),
        os.path.join(PROJECT_ROOT, 'mec_apps/rl_input_state.csv'),
    ]
    for p in paths:
        if os.path.exists(p):
            os.remove(p)
    print("✅ CSVs anteriores removidos.")


def start_metric_catcher_for_experiment():
    print("Iniciando MEC Metric Catcher...")
    open_terminal(
        'bash -c "source mec_app1/bin/activate && python3 mec_app_metric_catcher.py"',
        directory='mec_apps',
        title='Metric_Catcher_exp',
    )
    time.sleep(8)


def start_intelligence_for_experiment(controller_type: str):
    print(f"Iniciando MEC Intelligence (CONTROLLER_TYPE={controller_type}, MAB_ENABLE=true)...")
    # MAB_ENABLE=true força o caminho via controller (MAB ou RR via
    # CONTROLLER_TYPE) — caso contrário o inteligence cai num round-robin
    # legado interno que NÃO loga rewards.csv, fazendo o RR parecer "sem
    # latência" nos relatórios.
    cmd = (
        f'CONTROLLER_TYPE={controller_type} MAB_ENABLE=true bash -c '
        '"source mec_app1/bin/activate && python3 mec_app_inteligence.py"'
    )
    open_terminal(
        cmd,
        directory='mec_apps',
        title=f'MEC_Intelligence_{controller_type}',
    )
    time.sleep(15)


def start_mapeK_for_experiment():
    print("Iniciando MAPE-K...")
    open_terminal(
        'python3 mapeK.py',
        directory='mec_apps',
        title='mapeK_exp',
    )
    time.sleep(5)


def trigger_workload_in_container(scenario: str):
    """Dispara run_workload.sh dentro do container nr_ue."""
    log_path = f"/mnt/ueransim/workload_{scenario}_{int(time.time())}.log"
    cmd = (
        f'docker exec -d nr_ue bash -c '
        f'"chmod +x /mnt/ueransim/run_workload.sh && '
        f'/mnt/ueransim/run_workload.sh > {log_path} 2>&1"'
    )
    print(f"🚀 Disparando workload no nr_ue (log: {log_path})")
    subprocess.run(cmd, shell=True, check=True)


def stop_workload_in_container():
    print("Matando UEs e workload no container...")
    subprocess.run("docker exec nr_ue pkill -f ue_client.py",
                   shell=True, check=False)
    subprocess.run("docker exec nr_ue pkill -f run_workload.sh",
                   shell=True, check=False)
    time.sleep(5)


def cleanup_extra_mec_instances(keep_min: int = 2):
    """Mata containers mec_app1_instance<N> com N >= keep_min e remove o
    serviço correspondente do service_registry. Usar entre cenários pra
    evitar que MAPE-K do segundo cenário herde 10 instâncias do primeiro.

    Estratégia:
      1. docker ps lista os containers mec_app1_instance*
      2. Pra cada com índice >= keep_min, chama mec_instance_manager.py stop
         (que tira do registry E faz docker rm -f)
    """
    print(f"\n🧹 Cleanup de instâncias MEC extras (mantém 0..{keep_min - 1})...")
    try:
        result = subprocess.run(
            "docker ps --format '{{.Names}}' | grep '^mec_app1_instance' || true",
            shell=True, capture_output=True, text=True, check=False,
        )
        names = [n.strip() for n in result.stdout.splitlines() if n.strip()]
    except Exception as e:
        print(f"⚠️ Falha ao listar containers: {e}")
        return

    if not names:
        print("  (nenhum container mec_app1_instance encontrado)")
        return

    pat = re.compile(r"^mec_app1_instance(\d+)$")
    extras = []
    for name in names:
        m = pat.match(name)
        if not m:
            continue
        idx = int(m.group(1))
        if idx >= keep_min:
            extras.append(idx)

    if not extras:
        print(f"  ✅ Nada pra remover. {len(names)} instâncias dentro do limite.")
        return

    extras.sort(reverse=True)  # mata maiores primeiro pra manter contiguidade
    print(f"  Removendo {len(extras)} instância(s): {extras}")
    for idx in extras:
        container = f"mec_app1_instance{idx}"
        mec_name = f"VideoStreamingService{idx}"
        cmd = (
            f"python3 mec_instance_manager.py stop "
            f"{container} --mec_name {mec_name}"
        )
        try:
            subprocess.run(
                cmd, shell=True, cwd=_PROJECT_ROOT,
                check=False, timeout=20,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            # Fallback: force docker rm caso o stop tenha falhado parcialmente
            subprocess.run(
                f"docker rm -f {container}",
                shell=True, check=False, timeout=10,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            print(f"    ✓ {container} removido")
        except Exception as e:
            print(f"    ⚠️ falha removendo {container}: {e}")

    time.sleep(3)
    print("  ✅ Cleanup concluído.")


def wait_with_progress(duration_sec: int, label: str):
    print(f"⏳ {label}: aguardando {duration_sec/60:.0f} min...")
    start = time.time()
    last_pct = -1
    while True:
        elapsed = int(time.time() - start)
        if elapsed >= duration_sec:
            break
        pct = int(elapsed * 100 / duration_sec)
        if pct != last_pct:
            print(f"  [{pct:3d}%] {elapsed}/{duration_sec} s")
            last_pct = pct
        time.sleep(30)


def archive_run(scenario: str) -> str:
    timestamp = time.strftime('%Y%m%d_%H%M%S')
    run_dir = os.path.join(PROJECT_ROOT, 'runs', f'{scenario}_{timestamp}')
    os.makedirs(run_dir, exist_ok=True)

    rl_csv = os.path.join(PROJECT_ROOT, 'mec_apps/rl_input_state.csv')
    print(f"📋 Arquivando '{scenario}' — origem esperada: {rl_csv}")
    if os.path.exists(rl_csv):
        size = os.path.getsize(rl_csv)
        shutil.copy(rl_csv, os.path.join(run_dir, 'rl_input_state.csv'))
        graficos_csv = os.path.join(
            PROJECT_ROOT, 'graficos', f'rl_input_state_{scenario}.csv'
        )
        os.makedirs(os.path.dirname(graficos_csv), exist_ok=True)
        shutil.copy(rl_csv, graficos_csv)
        print(f"✅ rl_input_state.csv ({size} bytes) → {run_dir} e {graficos_csv}")
    else:
        print(f"⚠️ {rl_csv} NÃO foi gerado.")
        print(f"   Conteúdo de {os.path.dirname(rl_csv)}:")
        try:
            for f in sorted(os.listdir(os.path.dirname(rl_csv))):
                print(f"     - {f}")
        except OSError:
            print("     (diretório não existe)")
        print("   Verifique se mec_app_inteligence iniciou corretamente:")
        print(f"     tail -50 {os.path.join(_PROJECT_ROOT, 'logs', f'MEC_Intelligence_{scenario}.log')}")

    results_dir = os.path.join(PROJECT_ROOT, 'mec_apps/Results')
    if os.path.isdir(results_dir):
        dest = os.path.join(run_dir, 'Results')
        if os.path.exists(dest):
            shutil.rmtree(dest)
        shutil.copytree(results_dir, dest)

    return run_dir


def run_single_scenario(scenario: str, duration_min: int):
    print(f"\n{'='*60}\n  CENÁRIO {scenario.upper()}  ({duration_min} min)\n{'='*60}")

    # 1. Mata processos do cenário anterior (intelligence/catcher/mapeK)
    print(f"\n[1/7] Matando processos do cenário anterior...")
    for pat in ['mec_app_inteligence.py',
                'mec_app_metric_catcher.py',
                'mapeK.py']:
        kill_pattern(pat)
    time.sleep(5)
    print("  ✓ intelligence, catcher, mapeK encerrados")

    # 2. Cleanup de instâncias extras (volta ao estado inicial: 2 instâncias)
    #    Isso impede que MAB (que escalou até 10) deixe o cenário RR
    #    começando saturado em MAX_INSTANCES.
    print(f"\n[2/7] Cleanup de instâncias MEC extras...")
    cleanup_extra_mec_instances(keep_min=2)

    # 3. Limpa CSVs do experimento
    print(f"\n[3/7] Limpando CSVs antigos...")
    clean_experiment_csvs()

    # 4. Catcher
    print(f"\n[4/7] Iniciando MEC Metric Catcher...")
    start_metric_catcher_for_experiment()

    # 5. Intelligence (com CONTROLLER_TYPE)
    print(f"\n[5/7] Iniciando MEC Intelligence (CONTROLLER_TYPE={scenario})...")
    start_intelligence_for_experiment(scenario)

    # 6. MAPE-K (vai inicializar com 2 instâncias detectadas via /discover)
    print(f"\n[6/7] Iniciando MAPE-K (esperado: detectar 2 instâncias)...")
    start_mapeK_for_experiment()
    time.sleep(5)
    # Confere via service_registry quantas instâncias o MAPE-K vai ver
    try:
        resp = subprocess.run(
            "curl -sf --max-time 5 http://172.22.0.162/service_registry/v1/discover",
            shell=True, capture_output=True, text=True, check=False, timeout=8,
        )
        if resp.returncode == 0 and resp.stdout:
            import json as _json
            services = _json.loads(resp.stdout)
            vids = [s for s in services if s.get('type') == 'VidProc']
            print(f"  📊 Service registry: {len(vids)} VidProc ativos antes do workload")
            for s in vids:
                print(f"    - {s.get('name')}")
    except Exception as e:
        print(f"  ⚠️ Não consegui consultar service_registry: {e}")

    # 7. Dispara workload
    print(f"\n[7/7] Disparando workload phased...")
    try:
        trigger_workload_in_container(scenario)
    except subprocess.CalledProcessError as e:
        print(f"❌ Falha ao disparar workload: {e}")
        return None

    # Aguarda execução
    try:
        wait_with_progress(duration_min * 60, scenario.upper())
    except KeyboardInterrupt:
        print("\n⚠️ Interrompido pelo usuário — encerrando UEs...")
        stop_workload_in_container()
        raise

    # Para workload
    stop_workload_in_container()

    # Arquiva resultados
    return archive_run(scenario)


def generate_comparison_graphs():
    print(f"\n{'='*60}\n  GERANDO GRÁFICOS COMPARATIVOS\n{'='*60}")
    graphs_dir = os.path.join(_PROJECT_ROOT, 'graficos')
    script_path = os.path.join(graphs_dir, 'graficos_compare.py')

    # Confere existência dos CSVs antes de tentar plotar
    expected = [
        os.path.join(graphs_dir, 'rl_input_state_mab.csv'),
        os.path.join(graphs_dir, 'rl_input_state_rr.csv'),
    ]
    found = [p for p in expected if os.path.exists(p)]
    if not found:
        print(f"❌ Nenhum CSV de cenário em {graphs_dir}/")
        print("   Esperado: rl_input_state_mab.csv e/ou rl_input_state_rr.csv")
        return
    print("CSVs encontrados:")
    for p in found:
        print(f"  ✓ {p} ({os.path.getsize(p)} bytes)")

    try:
        subprocess.run(
            [sys.executable, script_path],
            cwd=graphs_dir,
            check=True,
        )
        print(f"✅ Gráficos em {graphs_dir}/relatorio_compare/")
    except subprocess.CalledProcessError as e:
        print(f"❌ graficos_compare.py falhou: {e}")
    except FileNotFoundError:
        print(f"❌ {sys.executable} não encontrado")


def ensure_base_mec_instances():
    """Garante exatamente 2 instâncias MEC base (0 e 1) rodando.

    Estratégia: força clean slate — remove TODOS os mec_app1_instance*
    e recria os 2 base. É a forma mais robusta de funcionar tanto após
    primeiro start (containers ausentes) quanto após Q/restart (podem
    ter sobrado lixo).
    """
    print("Garantindo 2 instâncias MEC base (recreate-from-clean)...")
    # 1. Remove TODOS os mec_app1_instance*
    subprocess.run(
        "docker ps -a --format '{{.Names}}' | grep '^mec_app1_instance' | "
        "xargs -r docker rm -f",
        shell=True, check=False, timeout=60,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    # 2. Reset do counter pra que start_mec_apps comece em 0
    process_manager.app_instance_counter = 0
    # 3. Sobe 2 frescos (0 e 1)
    start_mec_apps(2)
    # 4. Aguarda registrar no service_registry
    time.sleep(15)


def setup_stack_for_experiment():
    """Sobe (ou re-sobe) o stack inteiro. Idempotente.

    - Prometheus/Core/RAN/MEP/UE: docker-compose up é noop se já rodam
    - MEC base (0 e 1): força recreate via ensure_base_mec_instances()
    """
    print(f"\n{'='*60}\n  SETUP DO STACK\n{'='*60}")
    start_prometheus_grafana()
    start_core_environment()
    start_ran()
    start_mep_enviroment()
    ensure_base_mec_instances()
    start_ue()
    time.sleep(10)
    print("✅ Stack pronto.")


def _print_active_vidproc():
    """Mostra quantas instâncias VidProc o service_registry conhece agora."""
    try:
        resp = subprocess.run(
            "curl -sf --max-time 5 http://172.22.0.162/service_registry/v1/discover",
            shell=True, capture_output=True, text=True, check=False, timeout=8,
        )
        if resp.returncode == 0 and resp.stdout:
            import json as _json
            services = _json.loads(resp.stdout)
            vids = [s for s in services if s.get('type') == 'VidProc']
            print(f"  📊 Service registry: {len(vids)} VidProc ativo(s)")
            for s in vids:
                print(f"     - {s.get('name')}")
            return len(vids)
    except Exception as e:
        print(f"  ⚠️ Não consegui consultar service_registry: {e}")
    return None


def run_scenario_individual(scenario: str, duration_min: int):
    """Roda UM cenário do zero — self-contained.

    NÃO depende de você ter clicado a opção 1 antes. Faz tudo:
      1. Setup completo do stack (idempotente — recria as 2 instâncias base)
      2. Mata catcher/intelligence/mapeK que possam ter ficado vivos
      3. Limpa CSVs
      4. Sobe catcher → intelligence (CONTROLLER_TYPE=mab|rr) → mapeK
      5. Mostra estado do service_registry
      6. Dispara workload phased no nr_ue
      7. Aguarda duration_min minutos
      8. Para workload e arquiva resultados

    Você pode rodar opção 2, dar Q, restart, opção 3 → funciona igual.
    Você pode rodar opção 2 e em seguida 3 sem dar Q → também funciona.
    """
    print(f"\n{'='*60}\n  CENÁRIO {scenario.upper()} (self-contained, {duration_min} min)\n{'='*60}")

    # 1. Setup completo do stack — idempotente
    setup_stack_for_experiment()

    # 2. Mata catcher/intelligence/mapeK que possam ter sobrado de cenário
    #    anterior (se você vier de uma execução prévia ou opção 2 → 3 direto)
    print(f"\n[2/8] Matando catcher/intelligence/mapeK antigos (se houver)...")
    for pat in ['mec_app_inteligence.py',
                'mec_app_metric_catcher.py',
                'mapeK.py']:
        kill_pattern(pat)
    time.sleep(5)

    print("\n📋 Estado do service_registry após setup:")
    _print_active_vidproc()

    # 3. Limpa CSVs
    print(f"\n[3/8] Limpando CSVs antigos...")
    clean_experiment_csvs()

    # 4. Catcher
    print(f"\n[4/8] Iniciando MEC Metric Catcher...")
    start_metric_catcher_for_experiment()

    # 5. Intelligence
    print(f"\n[5/8] Iniciando MEC Intelligence (CONTROLLER_TYPE={scenario})...")
    start_intelligence_for_experiment(scenario)

    # 6. MAPE-K
    print(f"\n[6/8] Iniciando MAPE-K...")
    start_mapeK_for_experiment()
    time.sleep(5)
    print("\n📋 Estado do service_registry antes de disparar workload:")
    _print_active_vidproc()

    # 7. Dispara workload
    print(f"\n[7/8] Disparando workload phased no nr_ue...")
    try:
        trigger_workload_in_container(scenario)
    except subprocess.CalledProcessError as e:
        print(f"❌ Falha ao disparar workload: {e}")
        return None

    # 8. Aguarda + cleanup + arquiva
    print(f"\n[8/8] Aguardando {duration_min} min de execução...")
    try:
        wait_with_progress(duration_min * 60, scenario.upper())
    except KeyboardInterrupt:
        print("\n⚠️ Interrompido pelo usuário — encerrando UEs...")
        stop_workload_in_container()
        raise

    stop_workload_in_container()
    run_dir = archive_run(scenario)

    print(f"\n{'='*60}")
    print(f"  ✅ CENÁRIO {scenario.upper()} FINALIZADO")
    print(f"     Resultado:        {run_dir}")
    print(f"     CSV pra gráficos: graficos/rl_input_state_{scenario}.csv")
    print(f"{'='*60}")
    print("\n  PRÓXIMOS PASSOS:")
    print("    - Pode rodar opção 3 (RR) ou 2 (MAB) direto — setup é idempotente")
    print("    - Quando tiver os 2 cenários, opção 4 gera os gráficos")
    print(f"{'='*60}")
    return run_dir


def run_full_experiment_suite(duration_min: int = 60):
    """Roda o suite inteiro automaticamente: setup + MAB + RR + gráficos."""
    total_min = duration_min * 2
    print(f"\n{'='*60}")
    print(f"  SUITE COMPLETO — MAB vs Round Robin")
    print(f"  Duração de cada cenário: {duration_min} min")
    print(f"  Tempo total estimado:    {total_min} min ({total_min/60:.1f} h)")
    print(f"{'='*60}")

    confirm = input("Confirmar e iniciar? [s/N]: ").strip().lower()
    if confirm != 's':
        print("Cancelado.")
        return

    setup_stack_for_experiment()

    try:
        for scenario in ['mab', 'rr']:
            run_single_scenario(scenario, duration_min)
    finally:
        # Sempre tenta limpar o que ficou de pé
        for pat in ['mec_app_inteligence.py',
                    'mec_app_metric_catcher.py',
                    'mapeK.py']:
            kill_pattern(pat)
        stop_workload_in_container()
        cleanup_extra_mec_instances(keep_min=2)

    generate_comparison_graphs()

    print(f"\n{'='*60}")
    print(f"  SUITE FINALIZADO")
    print(f"  Resultados em runs/<scenario>_*/")
    print(f"  Gráficos em  graficos/relatorio_compare/")
    print(f"{'='*60}")

# ============================================================================
# MAIN MENU
# ============================================================================

def display_menu():
    """Display the main menu."""
    print("\n" + "="*60)
    print("MEC ORCHESTRATOR - MAIN MENU")
    print("="*60)
    print("1  - Setup standalone do stack (opcional — opções 2/3 já incluem)")
    print()
    print("--- Experimentos (cada um é SELF-CONTAINED — clica e roda tudo) ---")
    print("2  - Cenário MAB completo (setup + 60 min de teste)")
    print("3  - Cenário Round Robin completo (setup + 60 min de teste)")
    print("4  - Gerar gráficos comparativos MAB vs RR")
    print()
    print("--- Utilidades ---")
    print("5  - Cleanup: matar instâncias MEC extras (mantém só 0 e 1)")
    print("6  - Iniciar N instâncias MEC manualmente")
    print()
    print("q  - Shutdown geral e sair")
    print("="*60 + "\n")

def main():
    """Main menu loop."""
    # Anchor cwd no projeto pra garantir que comandos `docker-compose -f xxx`
    # com caminhos relativos achem os arquivos certos.
    os.chdir(_PROJECT_ROOT)
    print(f"📂 Working directory: {_PROJECT_ROOT}")

    while True:
        display_menu()
        choice = input("Select option: ").strip().lower()
        
        try:
            if choice == 'q':
                cleanup_and_exit()
            
            elif choice == '1':
                start_prometheus_grafana()
                start_core_environment()
                start_ran()
                start_mep_enviroment()
                start_mep_inteligence_plus_catcher()
                start_mec_apps(2)
                start_ue()
                time.sleep(5)
                start_mapeK()
                NUM_UES = 100
                DELAY = 5  # segundos

                cmd = f"""
                cd /mnt/ueransim &&
                for i in $(seq 1 {NUM_UES}); do
                echo "🚀 Iniciando UE $i"
                python3 ue_client.py $i > ue_$i.log 2>&1 &
                sleep {DELAY}
                done;
                wait
                """

                docker_cmd = [
                    "docker", "exec", "-d", "nr_ue",
                    "bash", "-c", cmd
                ]

                print("Executando comando no container...")
                subprocess.run(docker_cmd, check=True)

                print("Ues iniciadas com sucesso 🚀")
            elif choice == '2':
                # Cenário MAB INDIVIDUAL — você cuida de iniciar/parar manualmente
                duration_input = input(
                    "Duração em minutos [60]: "
                ).strip()
                duration_min = int(duration_input) if duration_input else 60
                run_scenario_individual('mab', duration_min)

            elif choice == '3':
                # Cenário Round Robin INDIVIDUAL
                duration_input = input(
                    "Duração em minutos [60]: "
                ).strip()
                duration_min = int(duration_input) if duration_input else 60
                run_scenario_individual('rr', duration_min)

            elif choice == '4':
                # Gera gráficos comparativos MAB vs RR a partir dos
                # rl_input_state_{mab,rr}.csv em graficos/
                generate_comparison_graphs()

            elif choice == '5':
                # Cleanup utilitário — mata containers mec_app1_instance{N>=2}
                cleanup_extra_mec_instances(keep_min=2)

            elif choice == '6':
                num = int(input("Número de instâncias para subir: "))
                start_mec_apps(num)

            elif choice == '7':
                if process_manager.app_instance_counter > 0:
                    process_manager.app_instance_counter -= 1
                    print(f"✅ Instance {process_manager.app_instance_counter} deleted.")
                else:
                    print("No instances to delete.")
            
            elif choice == '8':
                print("Running stress tests (1, 2, 3 instances)...")
                for num_instances in [1, 2, 3]:
                    run_stress_test_scenario(num_instances)
                    cleanup_and_exit()
            
            elif choice == '9':
                start_receptor()
            
            elif choice == '10':
                kill_last_receptor()
            else:
                print("Invalid option.")
        
        except ValueError:
            print("Invalid input. Please enter a number.")
        except Exception as e:
            print(f"Error: {e}")
        
        time.sleep(1)

if __name__ == "__main__":
    local_ip = get_local_ip()
    print(f"Detected local IP: {local_ip}")
    #update_env_files(local_ip)
    print("Environment ready.\n")
    main()