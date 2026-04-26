import subprocess
import argparse
import os
import requests
import random
def build_image():
    print("🔨 Building Docker image 'mec_app:latest'...")
    subprocess.run([
        "docker", "build",
        "-t", "mec_app:latest",
        "-f", "dockerfiles/Dockerfile",
        "."
    ], check=True)

def start_instance(name, port, py_file, mec_name="VideoStreamingService", mec_host=None):
    """
    Inicia um novo container Docker para uma aplicação MEC com limites fixos de memória e CPU.

    Args:
        name (str): Nome do container Docker.
        port (int): Porta para expor o serviço.
        py_file (str): Caminho para o arquivo Python da aplicação.
        mec_name (str): Nome do serviço MEC (para registro na plataforma).
        mec_host (str): Host da plataforma MEC.
    """
    mec_host = mec_host or os.environ.get("MEC_HOST", "127.0.0.1")
    abs_py_file = os.path.abspath(py_file)

    # --- Limites de Recursos Fixos ---
    FIXED_MEM_LIMIT = "512m"
    FIXED_MEM_RESERVATION = "256m"
    FIXED_CPU_LIMIT = "0.20" # <<< NOVO: Limite para meio núcleo de CPU (50%)

    print(f"🚀 Starting container '{name}' on port {port} with app '{py_file}'")
    print(f"   Recursos: Memória {FIXED_MEM_LIMIT} (Reserva {FIXED_MEM_RESERVATION}), CPU {FIXED_CPU_LIMIT} núcleos.")

    host_uploads = os.path.join(os.getcwd(), "uploads")  # pasta local no host
    os.makedirs(host_uploads, exist_ok=True)  # garante que exista

    cmd = [
    "docker", "run", "-d",
    "--name", name,
    "-v", f"{abs_py_file}:/app/app.py",
    "-v", f"{host_uploads}:/app/uploads",
    "-e", f"MEC_NAME={mec_name}",
    "-e", f"MEC_PORT={port}",
    "-e", f"MEC_HOST={mec_host}",
    "-e", "MEC_APP=app.py",
    "-p", f"{port}:{port}",
    "--network", "demo-oai-public-net",
    "--memory", FIXED_MEM_LIMIT,
    "--memory-reservation", FIXED_MEM_RESERVATION,
    "--cpus", FIXED_CPU_LIMIT,
    "--add-host", "host.docker.internal:host-gateway",  # <<< ADICIONE ESTA LINHA
    "mec_app:latest",
]


    print(f"Comando Docker: {' '.join(cmd)}")

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(f"Container '{name}' iniciado com sucesso com limites de recursos.")
    except subprocess.CalledProcessError as e:
        print(f"❌ Erro ao iniciar container '{name}': {e}")
        print(f"Stdout do Docker: {e.stdout.strip() if e.stdout else 'N/A'}")
        print(f"Stderr do Docker: {e.stderr.strip() if e.stderr else 'N/A'}")
        raise

def stop_instance(name, mec_name):
    print(f"🛑 Stopping and removing container '{mec_name}'")
    response = requests.get("http://192.168.70.2/service_registry/v1/discover")
    discovered_services = response.json()
    
    for service in discovered_services:
        print(service["uid"])
        print(mec_name)
        if mec_name in service["uid"]:
            print(f"🛑 Stopping and removing container '{mec_name}'")
            requests.delete("http://192.168.70.2/service_registry/v1/register/" + service["sid"])
    subprocess.run(["docker", "rm", "-f", name], check=True)
def show_logs(name):
    print(f"📜 Logs for container '{name}':\n")
    subprocess.run(["docker", "logs", "-f", name])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manage MEC Docker instances")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("build", help="Build the Docker image")

    start_parser = subparsers.add_parser("start", help="Start a new MEC instance")
    start_parser.add_argument("name", help="Container name")
    start_parser.add_argument("port", type=int, help="Port to expose")
    start_parser.add_argument("py_file", help="Python file to mount (e.g., mec_app1.py)")
    start_parser.add_argument("--mec_name", default="VideoStreamingService", help="MEC_NAME (default: VideoStreamingService)")
    start_parser.add_argument("--mec_host", help="MEC_HOST (default: env var MEC_HOST or 127.0.0.1)")

    stop_parser = subparsers.add_parser("stop", help="Stop and remove an instance")
    stop_parser.add_argument("name", help="Container name")
    stop_parser.add_argument("--mec_name", help="Container  mec name")

    args = parser.parse_args()

    if args.command == "build":
        build_image()
    elif args.command == "start":
        start_instance(
            args.name, 
            args.port, 
            args.py_file, 
            mec_name=args.mec_name, 
            mec_host=args.mec_host
        )
        show_logs(args.name)
    elif args.command == "stop":
        stop_instance(args.name, args.mec_name)
    else:
        parser.print_help()