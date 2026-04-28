import subprocess
import time
import signal
import sys
import socket
import os
import requests
import random
from dataclasses import dataclass
from typing import List, Tuple, Optional
from enum import Enum

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
    if directory:
        full_command = f'cd "{directory}" && {command}'
    else:
        full_command = command

    # Salva logs em arquivo em vez de DEVNULL
    log_file = f"logs/{title or 'process'}.log"
    os.makedirs("logs", exist_ok=True)

    with open(log_file, "w") as f:
        process = subprocess.Popen(
            full_command,
            shell=True,
            stdout=f,
            stderr=subprocess.STDOUT
        )

    print(f"Background command executed (PID: {process.pid}) → logs/{title or 'process'}.log")
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
# MAIN MENU
# ============================================================================

def display_menu():
    """Display the main menu."""
    print("\n" + "="*50)
    print("MEC ORCHESTRATOR - MAIN MENU")
    print("="*50)
    print("1  - Start Prometheus+Grafana -> Core components -> CM+MEP -> RAN")
    print("q  - Shutdown and Exit")
    print("="*50 + "\n")

def main():
    """Main menu loop."""
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
                NUM_UES = 5

                cmd = f"""
                cd /mnt/ueransim &&
                for i in $(seq 1 {NUM_UES}); do
                python3 ue_client.py $i > ue_$i.log 2>&1 &
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
                start_core_environment()
            
            elif choice == '3':
                num = int(input("Number of consumers: "))
                start_broadcaster([app_config.mec_name_template + "0"])
                for _ in range(num):
                    start_receptor()
            
            elif choice == '4':
                start_ran_and_ue()
            
            elif choice == '5':
                start_mep_and_intelligence()
            
            elif choice == '6':
                num = int(input("Number of instances to start: "))
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