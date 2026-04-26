import cv2
import base64
import requests
import time
import redis
import threading

url = "http://192.168.70.2/TimeService/upload"  # Endpoint do servidor

VIDEO_PATH = "/home/marcelo-victor/Downloads/BigBuckBunny_320x180.mp4"  # Caminho do vídeo
def listen_to_notifications(service_type):
    """Função que escuta notificações do Redis"""
    redis_client = redis.Redis(host="0.0.0.0", port=6379, decode_responses=True)
    pubsub = redis_client.pubsub()
    # AVEncoding', 'SigProc', 'Traffic', 'ML', 'ImgProc', 'VidProc', 'Compression', 'RadioNetworkInformation', 'LocalisationAPI', 'TrafficAPI'

    topic_to_subscribe = requests.get(f'http://192.168.70.2/traffic_inteligence/subscribe',json= {"app_type": service_type})
    topic_to_subscribe = topic_to_subscribe.text
    pubsub.subscribe(topic_to_subscribe)  # Inscreve-se no canal "notifications"
    
    print("📢 Aguardando notificações...")
    for message in pubsub.listen():
        if message["type"] == "message":
            global url
            print(f"novo endpoint {message['data']}")
            url = f'http://192.168.70.2/{message['data']}/upload'
thread = threading.Thread(target=listen_to_notifications, args=("VidProc",), daemon=True)
thread.start()

cap = cv2.VideoCapture(VIDEO_PATH)  # Abre o vídeo

while True:
    ret, frame = cap.read()
    if not ret:
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # Volta para o início do vídeo
        continue

        # Se quiser parar ao final do vídeo, use essa linha abaixo e comente a de cima:
        # break

    _, buffer = cv2.imencode(".jpg", frame)
    frame_base64 = base64.b64encode(buffer).decode("utf-8")

    # Envia o frame para o servidor
    try:
        requests.post(url, json={"frame": frame_base64}, timeout=0.5)
    except requests.exceptions.RequestException as e:
        print(f"Erro ao enviar frame: {e}")

    time.sleep(0.09)  # Ajuste para controlar a taxa de envio

cap.release()
print("Envio de vídeo concluído.")
