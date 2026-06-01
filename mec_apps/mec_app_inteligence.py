from flask import Flask, jsonify, request
import random
import requests
import threading
import time
import redis
from dotenv import load_dotenv
import os
import csv
from datetime import datetime
import json
import logging
import pickle # Adicionado para carregar o modelo e o scaler
import numpy as np # Adicionado para manipulação de arrays
from collections import deque # Adicionado para o histórico em memória
from mab_controller import controller

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('mec_intelligence')

# Load environment variables
load_dotenv()

# Global variables
topics = {}
topic_counter = 0
mec_metrics = {}
instances_to_shut_down = []
draining_instances = set()
instance_status = {}

# --- Variáveis GLOBAIS para o MODELO GRU e SCALER (NOVAS) ---
loaded_model = None
loaded_scaler = None
inference_params = {}
# buffer para armazenar os últimos dados necessários para a predição da GRU
# O maxlen será definido pelo 'best_look_back' do modelo treinado
metrics_history_buffer = deque(maxlen=100) # Valor inicial seguro, ajustado depois de carregar inference_params

# Configuration
cpu_percentage = 0
PORT = 8078
MEC_HOST = os.getenv("MEC_HOST", "10.0.0.186")
MEP_ADDRESS = os.getenv("MEP_ADDRESS", "192.168.70.2")
INTELIGENCE_PORT = PORT
CATCHER_PORT = 8081
MEC_REGISTRY_URL = f"http://{MEP_ADDRESS}/service_registry/v1/register"
METRICS_URL = f"http://{MEP_ADDRESS}/traffic_catcher/app_metrics"
METRICS_CSV_FILE = "rl_input_state.csv"
METRICS_POLLING_INTERVAL = 10  # seconds
variables_create_app = {"instance_numer":1}
create_app = {"container_name": "mec_app1_instance", "port": 8090, "py_file": "examples/mec_app1.py", "mec_name": "VideoStreamingService", "mec_host": "10.0.0.", "initial_ip":186, "instance_numer": 0}
m_controller = controller(
    latency_ref=100,
    num_arms=2
)
# --- CONFIGURAÇÃO DE INATIVIDADE ---
INACTIVITY_TIMEOUT = 30

# --- Métricas para o Input do GRU (4 FEATURES - ATUALIZADO) ---
CORE_METRICS_FOR_GRU_INPUT = [
    "cpu_percent(prometheus)",
    "memory_percent(prometheus)",
    "memory_used_mb(prometheus)",
    "throughput_kbps(prometheus)"
]

# --- Métricas para o CSV (Original, com latency_ms, etc.) ---
CORE_METRICS_FOR_CSV = [
    "cpu_percent(prometheus)",
    "memory_percent(prometheus)",
    "memory_used_mb(prometheus)",
    "queue_size",
    "network_rx_kbps",
    "network_tx_kbps",
    "throughput_kbps(prometheus)",
    "avg_latency_ms",
    "max_latency_ms",
    "min_latency_ms"
]
ue_connected = {}
service_latency_stats = {}
topic_latency_stats = {}

# --- Função auxiliar para carregar ativos de inferência (NOVA) ---
def load_assets(model_path, scaler_path, params_path):
    """Carrega o modelo, o scaler e os parâmetros de inferência."""
    try:
        with open(model_path, 'rb') as f:
            model = pickle.load(f)
        logger.info(f"Modelo carregado com sucesso de: {model_path}")

        with open(scaler_path, 'rb') as f:
            scaler = pickle.load(f)
        logger.info(f"Scaler carregado com sucesso de: {scaler_path}")

        with open(params_path, 'rb') as f:
            params = pickle.load(f)
        logger.info(f"Parâmetros de inferência carregados de: {params_path}")

        return model, scaler, params
    except FileNotFoundError as e:
        logger.error(f"Erro: Arquivo não encontrado ao carregar ativos de inferência. Verifique os caminhos. Erro: {e}")
        return None, None, None
    except Exception as e:
        logger.error(f"Erro ao carregar ativos de inferência: {e}")
        return None, None, None

def register_mec():
    """Register the MEC Intelligence service with the MEC platform"""
    
    mec_data = {
        "description": "MEC Intelligence",
        "endpoints": [
            {
                "description": "Return the best mecApp to access at the given moment",
                "method": "GET",
                "name": "choose_mecApp",
                "parameters": [],
                "path": "/choose_mecApp"
            },
            { # NOVO ENDPOINT REGISTRADO para CPU com predição
                "description": "Return current and predicted CPU percentage",
                "method": "GET",
                "name": "cpu_prediction",
                "parameters": [],
                "path": "/cpu_percent"
            }
        ],
        "host": MEC_HOST,
        "name": "traffic_inteligence",
        "path": "/apiFlask/v1",
        "port": INTELIGENCE_PORT,
        "sid": "Inteligence-unique-0",
        "type": "Traffic",
        "uid": "inteligence-unique-id-0"
    }

    try:
        response = requests.post(MEC_REGISTRY_URL, json=mec_data)
        response.raise_for_status()
        response_data = response.json()
        logger.info(f"MEC API registration successful: {response_data}")
    except Exception as e:
        logger.error(f"Error registering with MEC API: {e}")


def save_metrics_to_csv(metrics_data):
    """Save collected metrics to CSV file for reinforcement learning input state"""
    
    # Validate the metrics data
    if not metrics_data or "data" not in metrics_data:
        logger.warning(f"Invalid data for saving metrics: {metrics_data}")
        return
    
    file_exists = os.path.exists(METRICS_CSV_FILE)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    with open(METRICS_CSV_FILE, mode='a', newline='') as file:
        writer = csv.writer(file)
        
        # Create header if file doesn't exist
        if not file_exists:
            header = ["timestamp", "app_type", "num_services"]
            
            # Add columns for aggregated metrics
            for metric in CORE_METRICS_FOR_CSV: # USA CORE_METRICS_FOR_CSV
                metric_name = metric.split('(')[0] if '(' in metric else metric
                header.extend([
                    f"avg_{metric_name}",
                    f"max_{metric_name}",
                    f"min_{metric_name}"
                ])
            
            header.extend(["services_json", "ues_json"])
            writer.writerow(header)
        
        # Write data for each app_type
        for app_type, instances in metrics_data["data"].items():
            if not instances:
                continue
                
            row = [timestamp, app_type, len(instances)]
            services_dict = {}
            ue_dict = {}
            metric_values = {metric: [] for metric in CORE_METRICS_FOR_CSV} # USA CORE_METRICS_FOR_CSV
            
            for service_name, metrics in instances.items():
                services_dict[service_name] = {}
                
                for metric in CORE_METRICS_FOR_CSV: # USA CORE_METRICS_FOR_CSV
                    value = metrics.get(metric, "N/A")
                    services_dict[service_name][metric] = value
                    
                    if isinstance(value, (int, float)) and value != "N/A":
                        metric_values[metric].append(value)
                
                ue_array = []
                for topic in topics.values():
                    if topic["app"] == service_name:
                        ue_array.append(topic["user_id"])
                        ue_dict[service_name] = ue_array
                                
            for metric in CORE_METRICS_FOR_CSV: # USA CORE_METRICS_FOR_CSV
                values = [v for v in metric_values[metric] if isinstance(v, (int, float)) and v != "N/A"]
                
                avg_value = sum(values) / len(values) if values else "N/A"
                row.append(avg_value)
                
                max_value = max(values) if values else "N/A"
                row.append(max_value)
                
                min_value = min(values) if values else "N/A"
                row.append(min_value)
            
            row.append(json.dumps(services_dict))
            row.append(json.dumps(ue_dict))
            
            writer.writerow(row)
    
    logger.debug(f"Metrics saved to {METRICS_CSV_FILE}")


def format_metrics_json(raw_metrics):
    """
    Formats and normalizes the metrics JSON for better consistency and structure
    (Este código permanece o mesmo, pois ele apenas formata o RAW JSON)
    """
    if not raw_metrics or "data" not in raw_metrics:
        logger.warning("Invalid metrics format received")
        return raw_metrics
    
    formatted_data = {
        "data": {},
        "message": raw_metrics.get("message", "Metrics processed successfully"),
        "timestamp": raw_metrics.get("timestamp", datetime.now().isoformat())
    }
    
    for app_type, services in raw_metrics["data"].items():
        formatted_data["data"][app_type] = {}
        
        for service_name, metrics in services.items():
            formatted_service = {}
            
            for metric in [
                "avg_latency_ms", "container_name", "cpu_percent(metric)", 
                "cpu_percent(prometheus)", "current_fps", "drop_rate_percent",
                "frames_dropped", "frames_received", "frames_sent", 
                "last_updated", "memory_percent(metric)", 
                "memory_percent(prometheus)", "memory_total_mb(metric)",
                "memory_total_mb(prometheus)", "memory_used_mb(metric)",
                "memory_used_mb(prometheus)", "network_rx_kbps",
                "network_tx_kbps", "queue_size", "throughput_kbps(metric)",
                "throughput_kbps(prometheus)", "latency_ms"
            ]:
                if metric in metrics:
                    if isinstance(metrics[metric], (int, float, str)):
                        if metrics[metric] == "N/A":
                            formatted_service[metric] = "N/A"
                        else:
                            try:
                                if isinstance(metrics[metric], str) and metrics[metric].replace('.', '', 1).isdigit():
                                    if '.' in metrics[metric]:
                                        formatted_service[metric] = float(metrics[metric])
                                    else:
                                        formatted_service[metric] = int(metrics[metric])
                                else:
                                    formatted_service[metric] = metrics[metric]
                            except:
                                formatted_service[metric] = metrics[metric]
                    else:
                        formatted_service[metric] = metrics[metric]
                else:
                    formatted_service[metric] = "N/A"
            
            formatted_data["data"][app_type][service_name] = formatted_service
    
    return formatted_data

def cleanup_inactive_users():
    """Rotina para remover usuários inativos e publicar comando de parada via Redis."""
    global topics
    while True:
        current_time = time.time()
        topics_to_remove = []
        for topic_id, info in list(topics.items()):
            if "last_active_time" in info and (current_time - info["last_active_time"]) > INACTIVITY_TIMEOUT:
                topics_to_remove.append(topic_id)

        for topic_id in topics_to_remove:
            logger.info(f"Usuário {topic_id} inativo por muito tempo. Removendo.")
            try:
                redis_client.publish(topic_id, "STOP_STREAM") 
                logger.info(f"Comando 'STOP_STREAM' publicado para {topic_id}.")
            except Exception as e:
                logger.error(f"Falha ao publicar 'STOP_STREAM' para {topic_id}: {e}")

            del topics[topic_id]

        time.sleep(INACTIVITY_TIMEOUT / 2)

def metric_catcher():
    """Thread function to periodically fetch metrics from traffic catcher"""
    global mec_metrics, topics, cpu_percentage, metrics_history_buffer, loaded_model, inference_params
    global service_latency_stats, topic_latency_stats

    service_latency_stats = {}
    topic_latency_stats = {}
    while True:
        try:
            response = requests.get(METRICS_URL)
            response.raise_for_status()
            raw_metrics = response.json()

            mec_metrics = format_metrics_json(raw_metrics)
            topic_latency_stats.clear()
            service_latency_stats.clear()
            # open("mec_metrics.json", "w").write(json.dumps(mec_metrics)) # Remover ou usar apenas para debug


            for app_type, services in mec_metrics.get("data", {}).items():
                for service_name, metrics in services.items():

                    latency_data = metrics.get("latency_ms", {})

                    latencies = []

                    if isinstance(latency_data, dict):
                        for topic, info in latency_data.items():

                            if isinstance(info, dict):

                                latency = info.get("latency")

                                try:
                                    latency = float(latency)

                                    latencies.append(latency)

                                    topic_latency_stats[topic] = {
                                        "service": service_name,
                                        "latency": latency
                                    }

                                except:
                                    pass

                    if latencies:
                        service_latency_stats[service_name] = {
                            "avg": sum(latencies) / len(latencies),
                            "max": max(latencies),
                            "min": min(latencies)
                        }
            for app_type, services in mec_metrics.get("data", {}).items():
                for service_name, metrics in services.items():

                    stats = service_latency_stats.get(service_name)

                    if stats:
                        metrics["avg_latency_ms"] = stats["avg"]
                        metrics["max_latency_ms"] = stats["max"]
                        metrics["min_latency_ms"] = stats["min"]
                    else:
                        metrics["avg_latency_ms"] = "N/A"
                        metrics["max_latency_ms"] = "N/A"
                        metrics["min_latency_ms"] = "N/A"
            relevant_metrics = {}
            average_metrics = {}
            app_counts = {}

            for app_type in mec_metrics["data"].keys():
                if app_type == "VidProc": # Foco apenas em VidProc
                    app_list = [
                    app_name
                    for app_name in mec_metrics["data"][app_type]
                    if app_name not in draining_instances
                ]
                    app_counts[app_type] = len(app_list)
                    
                    relevant_metrics[app_type] = {}
                    average_metrics[app_type] = {}

                    if app_list:
                        for especific_app in app_list:
                            # Coletar as métricas na ordem exata que o GRU espera (4 FEATURES)
                            relevant_metrics[app_type][especific_app] = {
                                "cpu_percent(prometheus)": mec_metrics["data"][app_type][especific_app].get("cpu_percent(prometheus)", np.nan),
                                "memory_percent(prometheus)": mec_metrics["data"][app_type][especific_app].get("memory_percent(prometheus)", np.nan),
                                "memory_used_mb(prometheus)": mec_metrics["data"][app_type][especific_app].get("memory_used_mb(prometheus)", np.nan),
                                "throughput_kbps(prometheus)": mec_metrics["data"][app_type][especific_app].get("throughput_kbps(prometheus)", np.nan)
                            }
                            # Para cálculo de médias para o CSV, use CORE_METRICS_FOR_CSV para coletar todos
                            for metric_key_csv in CORE_METRICS_FOR_CSV: # Usar para as médias do CSV
                                value_csv = mec_metrics["data"][app_type][especific_app].get(metric_key_csv, "N/A")
                                if average_metrics[app_type].get(metric_key_csv) is None:
                                    average_metrics[app_type][metric_key_csv] = 0
                                if isinstance(value_csv, (int, float)) and value_csv != "N/A":
                                    average_metrics[app_type][metric_key_csv] += float(value_csv)
                                # else: logger.warning(f"Valor nao numerico para {metric_key_csv}: {value_csv}") # Debug se houver NaNs


            # open("mec_metrics_relevants.json", "w").write(json.dumps(relevant_metrics)) # Remover ou usar para debug

            for app_type in average_metrics:
                count = app_counts.get(app_type, 1)
                for metric_key in average_metrics[app_type]:
                    # Garante que a divisão não ocorra por zero se count for 0
                    if count > 0:
                        average_metrics[app_type][metric_key] /= count
                    else:
                        average_metrics[app_type][metric_key] = "N/A" # Se não houver apps para calcular a média


            # open("mec_metrics_average.json", "w").write(json.dumps(average_metrics)) # Remover ou usar para debug

            # --- ATUALIZAÇÃO DA VARIÁVEL GLOBAL cpu_percentage ---
            if "VidProc" in average_metrics and "cpu_percent(prometheus)" in average_metrics["VidProc"]:
                cpu_values = []

                for app in mec_metrics["data"]["VidProc"].values():
                    v = app.get("cpu_percent(prometheus)", np.nan)
                    if isinstance(v, (int, float)):
                        cpu_values.append(v)

                cpu_percentage = max(cpu_values) if cpu_values else "N/A"
            else:
                cpu_percentage = "N/A"
                logger.warning("Não foi possível calcular avg_cpu_percent para VidProc.")

            # --- ATUALIZAÇÃO DO HISTÓRICO EM MEMÓRIA PARA O GRU ---
            if loaded_model and "VidProc" in average_metrics: # Apenas atualiza se o modelo foi carregado com sucesso
                current_gru_input_sample = []
                # Garanta a ordem EXATA das features para o GRU:
                # 'avg_cpu_percent', 'avg_memory_percent', 'avg_memory_used_mb', 'avg_throughput_kbps'
                try:
                    # Usar .get() com um valor padrão (ex: 0 ou np.nan) para evitar KeyError
                    # ou TypeErrors se a métrica não existir ou não for numérica.
                    current_gru_input_sample.append(average_metrics["VidProc"].get("cpu_percent(prometheus)", np.nan))
                    current_gru_input_sample.append(average_metrics["VidProc"].get("memory_percent(prometheus)", np.nan))
                    current_gru_input_sample.append(average_metrics["VidProc"].get("memory_used_mb(prometheus)", np.nan))
                    current_gru_input_sample.append(average_metrics["VidProc"].get("throughput_kbps(prometheus)", np.nan))

                    # Verifica se alguma métrica essencial para o GRU é NaN antes de adicionar
                    if not any(np.isnan(x) for x in current_gru_input_sample):
                        metrics_history_buffer.append(np.array(current_gru_input_sample, dtype=np.float32))
                        logger.info(f"Amostra de métricas adicionada ao histórico GRU. Tamanho atual: {len(metrics_history_buffer)}")
                    else:
                        logger.warning("Amostra para histórico GRU contém NaN, não adicionada.")

                except Exception as e:
                    logger.error(f"Erro ao preparar ou adicionar amostra para histórico GRU: {e}")
            else:
                if not loaded_model:
                    logger.warning("Modelo GRU não carregado, histórico GRU não será atualizado.")
                # else: logger.warning("App_type 'VidProc' não encontrado nas métricas para histórico GRU.") # Este log ja existe acima

            # Update app assignments for all topics
            is_map_enable = (
                os.getenv("MAP_ENABLE", "true").lower() == "true"
            )
            i = 0
            for topic_id, topic in list(topics.items()):
                if "data" in mec_metrics and topic["app_type"] in mec_metrics["data"]:
                    app_list = list(mec_metrics["data"][topic["app_type"]])

                    if app_list:
                        if is_map_enable:
                            if m_controller.model.num_arms != len(app_list):
                                m_controller.set_num_arms(len(app_list))
                            current_app = topics[topic_id].get("app")

                            latency_info = topic_latency_stats.get(topic_id)

                            if latency_info and latency_info["service"] == current_app:

                                ue_latency = latency_info["latency"]

                                # 1. update do bandit
                                m_controller.update_model(
                                    userId=topic_id,
                                    state=[ue_latency]
                                )

                                # 2. escolha do MAB
                                action = m_controller.get_arm_ts(topic_id)
                                mec_app_choice = app_list[action]

                                selected_service = mec_app_choice

                                # 3. LOG COMPLETO (DEBUG REAL)
                                logger.info(
                                    "\n[MAB DEBUG]\n"
                                    f"topic={topic_id}\n"
                                    f"  current_service={current_app}\n"
                                    f"  latency={ue_latency:.2f}\n"
                                    f"  selected_arm={action}\n"
                                    f"  selected_service={selected_service}\n"
                                    "------------------------"
                                )

                            else:
                                # fallback normal (sem update do MAB)
                                action = m_controller.get_arm_ts(topic_id)
                                mec_app_choice = app_list[action]

                                logger.info(
                                    f"[MAB FALLBACK] topic={topic_id} app={mec_app_choice} (no latency update)"
                                )
                        else:
                            mec_app_choice = app_list[i]
                        i = (i + 1) % len(app_list)
                        topics[topic_id]["app"] = mec_app_choice
                        redis_client.publish(topic_id, mec_app_choice)
                    else:
                        logger.warning(f"Nenhum app disponível para app_type {topic['app_type']} para {topic_id}.")
                else:
                    logger.warning(f"Nenhum dado disponível para app_type {topic['app_type']} para {topic_id}. Não foi possível atribuir um app.")

            save_metrics_to_csv(mec_metrics)

        except requests.exceptions.RequestException as e:
            logger.error(f"Erro ao buscar métricas: {e}")
        except json.JSONDecodeError:
            logger.error("Resposta JSON inválida do endpoint de métricas")
        except Exception as e:
            logger.error(f"Erro na coleta de métricas: {e}")
        
        time.sleep(METRICS_POLLING_INTERVAL)


# Initialize Flask app
app = Flask(__name__)
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
redis_client = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)


@app.route('/hello-api', methods=['GET'])
def get_time():
    """Simple health check endpoint"""
    return jsonify({
        "status": "online",
        "service": "MEC Intelligence",
        "timestamp": datetime.now().isoformat()
    })

@app.route('/metrics', methods=['GET'])
def get_metrics():
    global cpu_percentage
    """Return the current metrics data"""
    return jsonify(mec_metrics)
@app.route('/subscribe', methods=['GET'])
def get_subscribe():
    """Subscribe to app_type updates and get a topic ID"""
    global topic_counter
    
    try:
        data = request.get_json()
        
        if not data or "app_type" not in data:
            return jsonify({"error": "Missing app_type parameter"}), 400
            
        topic_counter += 1
        topic_id = f"topic_{topic_counter}"
        
        topics[topic_id] = {
            "user_id": topic_id,
            "app": None,
            "status": "Online", 
            "app_type": data["app_type"],
            "last_active_time": time.time()
        }
        
        logger.info(f"New subscription: {topic_id} for app_type {data['app_type']}")
        return topic_id
        
    except Exception as e:
        logger.error(f"Error in subscribe endpoint: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/heartbeat', methods=['POST'])
def receive_heartbeat():
    """Recebe um heartbeat de um usuário para marcar como ativo"""
    try:
        data = request.get_json()
        topic_id = data.get("topic_id")

        if not topic_id:
            return jsonify({"error": "Missing topic_id"}), 400

        if topic_id in topics:
            topics[topic_id]["last_active_time"] = time.time()
            return jsonify({"status": "ok"}), 200
        else:
            return jsonify({"error": "Topic not found"}), 404
    except Exception as e:
        logger.error(f"Erro ao receber heartbeat: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/choose_mecApp', methods=['GET'])
def choose_mec_app():
    """Returns the best MEC app to access at the given moment"""
    app_type = request.args.get('app_type')
    
    if not app_type:
        return jsonify({"error": "Missing app_type parameter"}), 400
        
    if "data" in mec_metrics and app_type in mec_metrics["data"]:
        apps = mec_metrics["data"][app_type]
        
        if not apps:
            return jsonify({"error": f"No available services for app_type: {app_type}"}), 404
            
        best_app = None
        best_score = float('inf')
        
        for app_name, metrics in apps.items():
            try:
                cpu_load = float(metrics.get("cpu_percent(metric)", 100))
                mem_load = float(metrics.get("memory_percent(metric)", 100))
                network_rx = float(metrics.get("network_rx_kbps", 0))
                network_tx = float(metrics.get("network_tx_kbps", 0))
                queue_size = float(metrics.get("queue_size", 0))
                
                network_load = network_rx + network_tx
                
                score = (0.4 * cpu_load) + (0.3 * mem_load) + (0.2 * network_load) + (0.1 * queue_size)
                
                if score < best_score:
                    best_score = score
                    best_app = app_name
            except (ValueError, TypeError):
                continue
        
        if best_app:
            return jsonify({
                "recommended_app": best_app,
                "app_type": app_type,
                "score": best_score,
                "metrics": mec_metrics["data"][app_type][best_app],
                "timestamp": datetime.now().isoformat()
            })
    
    return jsonify({"error": f"No suitable services found for app_type: {app_type}"}), 404


@app.route("/publish", methods=["POST"])
def publish_message():
    """Publish a message to Redis notification channel"""
    try:
        data = request.json
        message = data.get("message", "No message provided")
        
        redis_client.publish("notifications", message)
        
        return jsonify({
            "status": "success",
            "message": "Message published!",
            "content": message
        })
    except Exception as e:
        logger.error(f"Error publishing message: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/cpu_percent", methods=["GET"])
def get_avg_percent():
    """Return the current metrics data"""
    global cpu_percentage, loaded_model, loaded_scaler, inference_params, metrics_history_buffer

    predicted_cpu_percent = "N/A" # Valor padrão se a predição não for possível

    if loaded_model and loaded_scaler and inference_params:
        best_look_back = inference_params.get('best_look_back')
        num_features = inference_params.get('num_features')
        target_feature_index = inference_params.get('target_feature_index')

        # Verificar se temos dados suficientes no buffer
        if len(metrics_history_buffer) >= best_look_back:
            try:
                # Pegar as últimas 'best_look_back' amostras do buffer
                input_sequence = np.array(list(metrics_history_buffer)[-best_look_back:], dtype=np.float32)

                # 1. Normalizar a sequência de entrada
                # O scaler espera um array 2D (num_samples, num_features)
                input_sequence_normalized = loaded_scaler.transform(input_sequence)

                # 2. Reshape para o formato do modelo (1, look_back, num_features)
                input_for_model = input_sequence_normalized.reshape(1, best_look_back, num_features)

                # 3. Fazer a previsão
                # O predict retorna um array como [[valor]], então [0][0] para pegar o escalar
                predicted_normalized = loaded_model.predict(input_for_model)[0][0]

                # 4. Inverter a normalização da previsão
                # Criar um array dummy com todas as features para o inverse_transform
                dummy_pred_normalized = np.zeros((1, num_features), dtype=np.float32)
                dummy_pred_normalized[0, target_feature_index] = predicted_normalized

                predicted_original_scale = loaded_scaler.inverse_transform(dummy_pred_normalized)[0, target_feature_index]
                predicted_cpu_percent = float(f"{predicted_original_scale:.2f}") # Formata para 2 casas decimais

            except Exception as e:
                logger.error(f"Erro ao fazer ou processar previsão GRU: {e}")
                predicted_cpu_percent = "Erro na Previsão"
        else:
            logger.info(f"Histórico insuficiente para previsão GRU. Necessário {best_look_back} amostras, mas temos {len(metrics_history_buffer)}.")
    else:
        logger.warning("Modelo GRU, scaler ou parâmetros de inferência não carregados. Não é possível fazer previsão.")


    return jsonify({
        "current_avg_cpu_percent": cpu_percentage,
        #"predicted_next_avg_cpu_percent": "N/A"
        "predicted_next_avg_cpu_percent": predicted_cpu_percent
    })

def reassign_topics_from_instance(app_type, instance_name):
    reassigned = []

    if "data" not in mec_metrics or app_type not in mec_metrics["data"]:
        return reassigned

    candidate_apps = [
        app
        for app in mec_metrics["data"][app_type].keys()
        if app != instance_name and app not in draining_instances
    ]

    if not candidate_apps:
        logger.warning(f"Sem apps candidatas para redistribuir tópicos de {instance_name}")
        return reassigned

    for topic_id, topic_info in list(topics.items()):
        if topic_info.get("app_type") == app_type and topic_info.get("app") == instance_name:
            new_app = random.choice(candidate_apps)
            topics[topic_id]["app"] = new_app
            redis_client.publish(topic_id, new_app)
            reassigned.append({
                "topic_id": topic_id,
                "old_app": instance_name,
                "new_app": new_app
            })

    return reassigned
    
import subprocess
@app.route("/shut_down_mec_app", methods=["POST"])
def shut_down_mec_app():
    global draining_instances, instance_status

    try:
        data = request.get_json() or {}
        app_type = data.get("app_type")
        instance_name = data.get("instance_name")
        container_name = data.get("container_name")

        if not app_type or not instance_name or not container_name:
            return jsonify({"error": "Missing app_type, instance_name or container_name"}), 400

        draining_instances.add(instance_name)
        instance_status[instance_name] = "draining"

        reassigned = reassign_topics_from_instance(app_type, instance_name)

        time.sleep(2)

        stop_cmd = [
            "python3",
            "../mec_instance_manager.py",
            "stop",
            container_name,
            "--mec_name",
            instance_name
        ]
        result = subprocess.run(stop_cmd, capture_output=True, text=True)

        if result.returncode != 0:
            draining_instances.discard(instance_name)
            instance_status[instance_name] = "active"
            return jsonify({
                "status": "error",
                "message": "Failed to stop instance",
                "stderr": result.stderr,
                "reassigned": reassigned
            }), 500

        instance_status[instance_name] = "dead"
        draining_instances.discard(instance_name)

        return jsonify({
            "status": "success",
            "instance_name": instance_name,
            "container_name": container_name,
            "reassigned": reassigned
        }), 200

    except Exception as e:
        logger.error(f"Error in shut_down_mec_app: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # --- CAMINHOS PARA O SEU MODELO E ATIVOS DE INFERÊNCIA ---
    # SUBSTITUA ESTES CAMINHOS PELOS REAIS DO SEU AMBIENTE!
    # Se você está no Colab, eles provavelmente estarão em /content/saved_inference_assets/
    # Exemplo: './Results/Model_Optuna-GRU_0_51_8_0.009778396777794504_9_relu_Adam/GRU_lb9_lr0.009778396777794504_bs8_acrelu_opAdam_05_12_2025_16_28_14.sav'
    MODEL_PATH = '/home/marcelo-victor/Downloads/ml_model_gru/Results/best_lighter_Model_Optuna-GRU_0_198_32_1.0100167086418738e-05_23_relu_Adam/GRU_lb23_lr1.0100167086418738e-05_bs32_acrelu_opAdam_07_02_2025_12_03_41.sav'
    SCALER_PATH = '/home/marcelo-victor/Downloads/ml_model_gru/saved_inference_assets/min_max_scaler.pkl'
    INFERENCE_PARAMS_PATH = '/home/marcelo-victor/Downloads/ml_model_gru/saved_inference_assets/inference_params.pkl'

    # Carregar modelo, scaler e parâmetros de inferência na inicialização do app
    logger.info("Carregando modelo GRU, scaler e parâmetros de inferência...")
    loaded_model, loaded_scaler, inference_params = load_assets(MODEL_PATH, SCALER_PATH, INFERENCE_PARAMS_PATH)

    if loaded_model is None or loaded_scaler is None or inference_params is None:
        logger.error("Falha ao carregar ativos de inferência. A predição não estará disponível.")
    else:
        # Ajusta o maxlen do buffer de histórico com o look_back do modelo carregado
        metrics_history_buffer = deque(maxlen=inference_params['best_look_back'])
        logger.info(f"Buffer de histórico GRU inicializado com maxlen: {metrics_history_buffer.maxlen}")


    # Register with MEC platform
    register_mec()
    logger.info(f"Starting MEC Intelligence on {MEC_HOST}:{PORT}")
    
    # Start metrics collection thread
    metrics_thread = threading.Thread(target=metric_catcher, daemon=True)
    metrics_thread.start()
    cleanup_thread = threading.Thread(target=cleanup_inactive_users, daemon=True)
    cleanup_thread.start()
    # Start Flask app
    app.run(host=MEC_HOST, port=PORT, threaded=True)