import redis
import requests
import threading
import time
count =0 
def listen_to_notifications():
    """Função que escuta notificações do Redis"""
    redis_client = redis.Redis(host="0.0.0.0", port=6379, decode_responses=True)
    pubsub = redis_client.pubsub()
    # AVEncoding', 'SigProc', 'Traffic', 'ML', 'ImgProc', 'VidProc', 'Compression', 'RadioNetworkInformation', 'LocalisationAPI', 'TrafficAPI'

    topic_to_subscribe = requests.get(f'http://192.168.70.2/traffic_inteligence/subscribe',json= {"app_type": "RadioNetworkInformation"})
    topic_to_subscribe = topic_to_subscribe.text
    pubsub.subscribe(topic_to_subscribe)  # Inscreve-se no canal "notifications"
    
    print("📢 Aguardando notificações...")
    for message in pubsub.listen():
        if message["type"] == "message":
            global count
            count = 0
            print(f"\n🔔 Notificação recebida: {message['data']}")

def print_numbers():
    """Função que imprime números de 1 a 4 continuamente"""
    global count
    while True:
        print(count, end=" ", flush=True)
        count = count + 1
        time.sleep(1)

# Criar e iniciar a thread para escutar notificações
thread = threading.Thread(target=listen_to_notifications, daemon=True)
thread.start()

# Executar a função de impressão
print_numbers()
