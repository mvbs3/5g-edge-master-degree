from flask import Flask, jsonify, request
import random
import requests
import datetime
import threading
import time
import json
from dotenv import load_dotenv
import os

load_dotenv()
TIME_TO_COLLECT=3
MEC_HOST = os.getenv("MEC_HOST", "10.0.0.186")
MEP_ADDRESS = os.getenv("MEC_HOST", "192.168.70.2")
PROMETHEUS_URL = f"http://{MEC_HOST}:9090"
mec_apps_found = {}
latency_samples = {}
def query_prometheus(promql_query):
    try:
        response = requests.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": promql_query})
        result = response.json()
        if result["status"] == "success":
            results = result["data"]["result"]
            if results:
                value = float(results[0]["value"][1])
                return value
        return None
    except Exception as e:
        print(f"Erro consultando Prometheus: {e}")
        return None

def get_container_metrics(container_name):
    cpu_query = f'rate(container_cpu_usage_seconds_total{{name="{container_name}"}}[1m]) * 100'
    memory_usage_query = f'container_memory_max_usage_bytes{{name="{container_name}", image!=""}}'
    memory_limit_query = f'container_spec_memory_limit_bytes{{name="{container_name}"}}'
    host_memory_query = 'node_memory_MemTotal_bytes'  # Memória total do host

    # Network metrics queries
    network_rx_query = f'rate(container_network_receive_bytes_total{{name="{container_name}"}}[1m])'
    network_tx_query = f'rate(container_network_transmit_bytes_total{{name="{container_name}"}}[1m])'

    # Consultando métricas do Prometheus
    cpu_usage = query_prometheus(cpu_query)
    memory_usage_bytes = query_prometheus(memory_usage_query)
    memory_limit_bytes = query_prometheus(memory_limit_query)
    host_memory_bytes = query_prometheus(host_memory_query)  # Memória total do host
    network_rx_bps = query_prometheus(network_rx_query)
    network_tx_bps = query_prometheus(network_tx_query)

    '''
    print(cpu_usage)
    print(memory_usage_bytes)
    print(memory_limit_bytes)
    print(host_memory_bytes)
    '''
    memory_percent = None
    memory_used_mb = None
    memory_total_mb = None

    # Se o limite de memória for zero, usar a memória total do host
    if memory_limit_bytes == 0 and host_memory_bytes:
        memory_limit_bytes = host_memory_bytes

    if memory_usage_bytes and memory_limit_bytes:
        memory_percent = (memory_usage_bytes / memory_limit_bytes) * 100
        memory_used_mb = memory_usage_bytes / (1024 ** 2)
        memory_total_mb = memory_limit_bytes / (1024 ** 2)

    network_rx_kbps = None
    network_tx_kbps = None

    if network_rx_bps:
        network_rx_kbps = network_rx_bps / 1024  # Convert to Kbps
    
    if network_tx_bps:
        network_tx_kbps = network_tx_bps / 1024  # Convert to Kbps
    return {
        "cpu_percent": round(cpu_usage, 2) if cpu_usage is not None else "N/A",
        "memory_percent": round(memory_percent, 2) if memory_percent is not None else "N/A",
        "memory_used_mb": round(memory_used_mb, 2) if memory_used_mb is not None else "N/A",
        "memory_total_mb": round(memory_total_mb, 2) if memory_total_mb is not None else "N/A",
        "network_rx_kbps": round(network_rx_kbps, 2) if network_rx_kbps is not None else "N/A",
        "network_tx_kbps": round(network_tx_kbps, 2) if network_tx_kbps is not None else "N/A",
        "throughput_kbps": round((network_rx_kbps or 0) + (network_tx_kbps or 0), 2) if network_rx_kbps is not None and network_tx_kbps is not None else "N/A",

    }
def register_mec():
    mec_data = {
        "description": "MEC Inteligence",
        "endpoints": [
            {
                "description": "Get current metrics for all MEC Apps",
                "method": "GET",
                "name": "app_metrics",
                "parameters": [],
                "path": "/app_metrics"
            },
            {
                "description": "Hello world test endpoint",
                "method": "GET",
                "name": "hello_api",
                "parameters": [],
                "path": "/hello-api"
            }
        ],
        "host": MEC_HOST,
        "name": "traffic_catcher",
        "path": "/apiFlask/v1",
        "port": 8079,
        "sid": "traffic-unique-0",
        "type": "Traffic",
        "uid": "traffic-unique-id-0"
    }

    mec_url = f"http://{MEP_ADDRESS}/service_registry/v1/register"

    try:
        response = requests.post(mec_url, json=mec_data)
        response.raise_for_status()
        response_data = response.json()
        print("Registro na API MEC bem-sucedido:", response_data)
    except Exception as e:
        print("Erro ao registrar na API MEC:", e)

register_mec()

app = Flask(__name__)
def get_container_name_by_id(container_id):
    try:
        import subprocess
        import json
        
        # Usar docker inspect para obter informações do container
        result = subprocess.run(
            ["docker", "inspect", "--format='{{.Name}}'", container_id],
            capture_output=True,
            text=True,
            check=True
        )
        
        # A saída do docker inspect com o formato especificado retorna o nome com / no início
        container_name = result.stdout.strip().strip("'\"").lstrip('/')
        print(f"Container name: {container_name}")
        return container_name
    except subprocess.CalledProcessError as e:
        print(f"Erro ao executar docker inspect: {e}")
        print(f"Stderr: {e.stderr}")
        return "N/a"
    except Exception as e:
        print(f"Erro ao tentar obter o nome do container: {e}")
        return "N/a"

def metric_catcher():
    """Main thread to continuously collect metrics from MEC apps"""
    while True:
        try:
            # Discover available MEC services
            response = requests.get(f"http://{MEP_ADDRESS}/service_registry/v1/discover")
            discovered_services = response.json()
            
            for service in discovered_services:
                service_type = service["type"]
                service_name = service["name"]
                
                # Initialize type and service in our metrics dictionary if not exists
                if not mec_apps_found.get(service_type):
                    mec_apps_found[service_type] = {}

                if not mec_apps_found[service_type].get(service_name):
                    mec_apps_found[service_type][service_name] = {}

                try:
                    # Skip collecting metrics for our own service and intelligence service
                    if service_type != "Traffic":
                        # Get service's own metrics
                        metric_response = requests.get(f'http://{MEP_ADDRESS}/{service_name}/metric', timeout=2)
                        metric_data = metric_response.json()
                        
                        # Get container name for Prometheus metrics
                        container_name = get_container_name_by_id(metric_data.get("container_id", "N/A"))
                        
                        # Get Prometheus metrics if container name is available
                        prometheus_metrics = get_container_metrics(container_name) if container_name != "N/A" else {
                            "cpu_percent": "N/A",
                            "memory_percent": "N/A",
                            "memory_used_mb": "N/A",
                            "memory_total_mb": "N/A",
                            "network_rx_kbps": "N/A",
                            "network_tx_kbps": "N/A",
                            "throughput_kbps": "N/A"
                        }
                        latency_ms = [{topic: info["latency"]} for topic, info in latency_samples.items() if info["app"] == service_name]
                        
                        # Update metrics in our dictionary
                        mec_apps_found[service_type][service_name] = {
                            "container_name": container_name,
                            "queue_size": metric_data.get("active_requests", 0),
                            
                            # Video streaming specific metrics
                            "frames_received": metric_data.get("frames_received", 0),
                            "frames_dropped": metric_data.get("frames_dropped", 0),
                            "frames_sent": metric_data.get("frames_sent", 0),
                            "current_fps": metric_data.get("current_fps", 0),
                            "avg_latency_ms": metric_data.get("avg_latency_ms", 0),
                            "drop_rate_percent": metric_data.get("drop_rate_percent", 0),
                            
                            # System metrics from both sources
                            "cpu_percent(prometheus)": prometheus_metrics.get("cpu_percent", "N/A"),
                            "cpu_percent(metric)": metric_data.get("cpu_percent", "N/A"),
                            "memory_percent(prometheus)": prometheus_metrics.get("memory_percent", "N/A"),
                            "memory_percent(metric)": metric_data.get("memory_percent", "N/A"),
                            "memory_used_mb(prometheus)": prometheus_metrics.get("memory_used_mb", "N/A"),
                            "memory_used_mb(metric)": metric_data.get("memory_used_mb", "N/A"),
                            "memory_total_mb(prometheus)": prometheus_metrics.get("memory_total_mb", "N/A"),
                            "memory_total_mb(metric)": metric_data.get("memory_total_mb", "N/A"),
                            
                            # Network metrics from Prometheus
                            "network_rx_kbps": prometheus_metrics.get("network_rx_kbps", "N/A"),
                            "network_tx_kbps": prometheus_metrics.get("network_tx_kbps", "N/A"),
                            "throughput_kbps(prometheus)": prometheus_metrics.get("throughput_kbps", "N/A"),
                            "throughput_kbps(metric)": metric_data.get("throughput_kbps", "N/A"),
                            "latency_ms": latency_samples if latency_samples else "N/A",
                            # Last updated timestamp
                            "last_updated": datetime.datetime.now().isoformat()
                        }
                        
                        print(f"[OK] Metrics collected for {service_name}")
                    else:
                        # For our own service, just update a basic entry
                        mec_apps_found[service_type][service_name]["queue_size"] = "N/A"
                except Exception as e:
                    print(f"[METRIC ERROR] {service_name}: {e}")
                    # Mark the service as having no metrics available
                    mec_apps_found[service_type][service_name]["queue_size"] = "No Metric"
                    mec_apps_found[service_type][service_name]["error"] = str(e)
                    
            # Print current metrics summary
            print("\n===== CURRENT MEC APPLICATION METRICS =====")
            for app_type, apps in mec_apps_found.items():
                for app_name, metrics in apps.items():
                    print(f"App: {app_name} (Type: {app_type})")
                    # Print key metrics
                    key_metrics = ["queue_size", "cpu_percent(prometheus)", "memory_percent(prometheus)", 
                                 "network_rx_kbps", "network_tx_kbps","throughput_kbps(prometheus)","latency_ms"]
                    
                    for metric_name in key_metrics:
                        if metric_name in metrics:
                            print(f"     • {metric_name}: {metrics[metric_name]}")
            print("===========================================\n")
            
        except Exception as e:
            print("[GENERAL ERROR] Service discovery failed:", e)

        # Wait before next collection
        time.sleep(TIME_TO_COLLECT)

thread = threading.Thread(target=metric_catcher, daemon=True)
thread.start()

@app.route('/hello-api', methods=['GET'])
def get_time():
    return "Hello World2"
@app.route('/latency', methods=['POST'])
def save_latency():
    global latency_samples 
    data = request.json
    latency_ms = data.get('latency')
    topic = data.get('topic')
    app = data.get('app')
    if topic not in latency_samples:
        latency_samples[topic] = {}
    latency_samples[topic]={"app": app, "latency": latency_ms}
    
    return 'Latency saved', 200

@app.route('/app_metrics', methods=['GET'])
def receive_patient_data():
    return jsonify({"message": "Metricas enviadas com sucesso", "data": mec_apps_found, "timestamp": datetime.datetime.now().isoformat()})

if __name__ == '__main__':
    print(f"Starting MEC Catcher service on port 8079")
    print(f"Prometheus URL: {PROMETHEUS_URL}")
    app.run(host=MEC_HOST, port=8079)