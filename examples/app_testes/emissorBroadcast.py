import cv2
import base64
import requests
import time
import sys
import threading # <<< NOVO: Para a thread de monitoramento
import json      # <<< NOVO: Para parsear JSON
import os        # Para MEC_HOST

VIDEO_PATH = "/home/marcelo-victor/Downloads/BigBuckBunny_320x180.mp4"

# Define a URL base para construir os endpoints
BASE_URL_PREFIX = "http://192.168.70.2/" # IP da sua plataforma MEC
BASE_URL_SUFFIX = "/upload"

# URL do endpoint da sua MEC Intelligence para obter métricas/serviços ativos
# Assumimos que o endpoint /metrics da MEC Intelligence retorna as informações necessárias
# OU, idealmente, você teria um endpoint como /active_video_services
MEC_INTELLIGENCE_METRICS_URL = "http://192.168.70.2/traffic_inteligence/metrics" # <<< NOVO
# MEC_INTELLIGENCE_DISCOVER_URL = "http://192.168.70.2/service_registry/v1/discover" # Alternativa: consultar o service registry direto, mas a inteligência é melhor

MONITORING_INTERVAL = 10 # <<< NOVO: Frequência de verificação de novos serviços (em segundos)

# Variável global para a lista de URLs. Será modificada pela thread de monitoramento.
# Usamos um lock para garantir segurança ao acessar 'urls' de threads diferentes.
global_urls_lock = threading.Lock()
urls = [] # Inicialmente vazia ou com uma default, será preenchida pelo monitor


def get_initial_urls_from_arguments():
    """
    Parses command-line arguments to construct an initial list of URLs.
    This will be used if the monitoring thread hasn't found any services yet.
    It's good for ensuring the emitter starts with something if services are already up.
    """
    initial_urls = []
    if len(sys.argv) > 1:
        print("Arguments received. Constructing initial URLs from arguments...")
        for arg in sys.argv[1:]:
            if arg.startswith("VideoStreamingService"):
                url = f"{BASE_URL_PREFIX}{arg}{BASE_URL_SUFFIX}"
                initial_urls.append(url)
            else:
                print(f"Warning: Argument '{arg}' does not start with 'VideoStreamingService' and will be skipped.")
        if not initial_urls:
            print("No valid 'VideoStreamingService' arguments found. Starting with empty URL list.")
    else:
        print("No arguments received. Starting with empty URL list. Will discover services.")
    return initial_urls

# Preenche a lista de URLs inicial com base nos argumentos
urls = get_initial_urls_from_arguments()
print(f"URLs iniciais (pode ser vazia): {urls}")


# <<< NOVO: FUNÇÃO PARA MONITORAR NOVOS SERVIÇOS MEC >>>
def monitor_mec_services():
    global urls # Acessa a lista global de URLs
    
    # Dicionário para manter o controle dos serviços conhecidos e evitar atualizações desnecessárias
    known_services = set() 

    while True:
        try:
            # Consulta a MEC Intelligence para obter métricas/serviços ativos
            # Assumimos que MEC_INTELLIGENCE_METRICS_URL retorna um JSON com a estrutura
            # {"data": {"VidProc": {"VideoStreamingService0": {...}, "VideoStreamingService1": {...}}}}
            response = requests.get(MEC_INTELLIGENCE_METRICS_URL, timeout=5)
            response.raise_for_status() # Lança exceção para status HTTP de erro
            metrics_data = response.json()

            new_discovered_urls = []
            
            # Navega na estrutura JSON para encontrar os serviços VidProc
            if "data" in metrics_data and "VidProc" in metrics_data["data"]:
                video_services = metrics_data["data"]["VidProc"]
                for service_name in video_services.keys():
                    # Constrói a URL completa para o endpoint de upload
                    service_url = f"{BASE_URL_PREFIX}{service_name}{BASE_URL_SUFFIX}"
                    new_discovered_urls.append(service_url)
            
            # Compara a nova lista com a lista atual
            current_urls_set = set(new_discovered_urls)
            
            # Se a lista de serviços mudou, atualiza a lista global
            if current_urls_set != known_services:
                with global_urls_lock: # Usa o lock para garantir segurança na escrita
                    urls.clear() # Limpa a lista atual
                    urls.extend(list(current_urls_set)) # Adiciona os novos
                    known_services = current_urls_set # Atualiza os serviços conhecidos
                print(f"✅ URLs de serviço atualizadas: {urls}")
            else:
                # print("Nenhuma mudança nos serviços MEC. URLs inalteradas.") # Comentar para evitar excesso de logs
                pass

        except requests.exceptions.RequestException as e:
            print(f"⚠️ Erro ao consultar MEC Intelligence ({MEC_INTELLIGENCE_METRICS_URL}): {e}")
        except json.JSONDecodeError:
            print(f"⚠️ Erro ao decodificar JSON da MEC Intelligence. Resposta inválida.")
        except Exception as e:
            print(f"❌ Erro inesperado no monitor de serviços MEC: {e}")
        
        time.sleep(MONITORING_INTERVAL) # Espera antes da próxima verificação


# --- INICIA A THREAD DE MONITORAMENTO ---
# Esta thread rodará em segundo plano, atualizando a lista `urls`
monitor_thread = threading.Thread(target=monitor_mec_services, daemon=True)
monitor_thread.start()

cap = cv2.VideoCapture(VIDEO_PATH)  # Abre o vídeo

while True:
    ret, frame = cap.read()
    if not ret:
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # Recomeça o vídeo do início
        continue

    _, buffer = cv2.imencode(".jpg", frame)
    frame_base64 = base64.b64encode(buffer).decode("utf-8")

    timestamp = time.time()  # Timestamp atual em segundos (float)

    data = {
        "frame": frame_base64,
        "timestamp": timestamp
    }

    # <<< Usa o lock ao ler a lista 'urls' >>>
    with global_urls_lock: 
        # Itera sobre uma cópia da lista de URLs para evitar problemas se ela for modificada
        # enquanto o loop está em execução.
        urls_to_send = list(urls) 

    if not urls_to_send:
        print("Aviso: Nenhuma URL de serviço MEC disponível para enviar frames. Aguardando descoberta...")
        time.sleep(1) # Pequena pausa para evitar loop muito rápido
        continue # Pula para a próxima iteração do loop principal

    for url in urls_to_send:
        try:
            requests.post(url, json=data, timeout=0.5)
        except requests.exceptions.RequestException as e:
            # print(f"Erro ao enviar frame para {url}: {e}") # Comentar para evitar excesso de logs
            pass # Apenas evita que um erro em um endpoint pare o emissor

    time.sleep(0.09)  # Controla a taxa de envio (aprox. 11 FPS)

cap.release()
print("Envio de vídeo concluído.")