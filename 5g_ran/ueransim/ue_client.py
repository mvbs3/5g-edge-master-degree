# ue_client.py
import requests
import threading
import time
import redis
import json
import os
import random
import sys

# valor padrão
UE_ID = "1"

# se passou argumento
if len(sys.argv) > 1:
    UE_ID = sys.argv[1]
 
print(f"ue_id = {UE_ID}")

MEP_ADDRESS = os.getenv("MEP_ADDRESS", "172.22.0.162")
REDIS_HOST = os.getenv("MEC_HOST", "150.161.121.210")
APP_TYPE = os.getenv("APP_TYPE", "VidProc")

endpoint = os.getenv("INITIAL_ENDPOINT", f"http://{MEP_ADDRESS}/VideoStreamingService0")

# Carga por UE. "uniforme" é o comportamento original (mab/rr): toda UE igual e o
# /infer só dorme. "heterogeneo" (cenários *_lat) dá a cada UE um perfil fixo — a UE
# manda X-Work-Ms e a instância gasta esse tempo de CPU por requisição.
#   perfil   fração   intervalo entre requisições   CPU por requisição
#   leve      50%     0.5–1.0 s                      4 ms   (~5 ms de CPU/s)
#   medio     30%     0.3–0.6 s                      8 ms   (~18 ms/s)
#   pesado    20%     0.2–0.4 s                      12 ms  (~40 ms/s)
# Média ~16 ms/s por UE: 100 UEs ≈ 1.6 s de CPU/s ≈ 8 instâncias de --cpus 0.20 cheias.
# O sorteio usa o UE_ID como semente, então a UE 37 tem o mesmo perfil no MAB e no RR.
LOAD_PROFILE = os.getenv("LOAD_PROFILE", "uniforme").lower()
PROFILES = {
    "leve":   {"interval": (0.5, 1.0), "work_ms": 4},
    "medio":  {"interval": (0.3, 0.6), "work_ms": 8},
    "pesado": {"interval": (0.2, 0.4), "work_ms": 12},
}
if LOAD_PROFILE == "heterogeneo":
    _sorteio = random.Random(int(UE_ID) if UE_ID.isdigit() else UE_ID).random()
    PROFILE_NAME = "leve" if _sorteio < 0.5 else "medio" if _sorteio < 0.8 else "pesado"
    PROFILE = PROFILES[PROFILE_NAME]
    print(f"[UE {UE_ID}] perfil de carga: {PROFILE_NAME} {PROFILE}")
else:
    PROFILE_NAME, PROFILE = "uniforme", None

lock = threading.Lock()
topic_id = None

# Mensagem que o reaper da inteligência publica quando dá a UE como inativa
# (mec_app_inteligence.py:337). Não é nome de serviço.
STOP_STREAM = "STOP_STREAM"


def listen_updates():
    """Inscreve a UE num topic e segue o endpoint escolhido pelo MAB/RR.

    Nunca morre: se o Redis ou o /subscribe falharem, tenta de novo. Se a UE receber
    STOP_STREAM estando viva (o reaper a removeu porque os heartbeats não chegaram),
    ela se reinscreve num topic novo em vez de passar a chamar /STOP_STREAM/...
    """
    global endpoint, topic_id
    session = requests.Session()

    while True:
        try:
            r = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)
            pubsub = r.pubsub()

            response = session.get(
                f"http://{MEP_ADDRESS}/traffic_inteligence/subscribe",
                json={"app_type": APP_TYPE},
                timeout=5
            )
            response.raise_for_status()

            new_topic = response.text.strip()
            pubsub.subscribe(new_topic)
            topic_id = new_topic

            print(f"[UE {UE_ID}] Inscrito no topic: {topic_id}")

            for message in pubsub.listen():
                if message["type"] != "message":
                    continue

                service_name = message["data"]

                if service_name == STOP_STREAM:
                    print(f"[UE {UE_ID}] {STOP_STREAM} recebido em {topic_id} — reinscrevendo")
                    break

                with lock:
                    endpoint = f"http://{MEP_ADDRESS}/{service_name}"
                    print(f"[UE {UE_ID}] Novo endpoint: {endpoint}")

            pubsub.close()

        except Exception as e:
            print(f"[UE {UE_ID}] Erro na inscrição: {e} — tentando de novo em 2 s")
            time.sleep(2)


# Cada thread usa a própria Session (Session não é thread-safe). Sem keep-alive, cada
# request abria uma conexão TCP nova; com 100 UEs isso esgotava as portas efêmeras do
# nr_ue ("[Errno 99] Cannot assign requested address") e todas as UEs paravam juntas.
def heartbeat_loop():
    global topic_id
    session = requests.Session()

    while True:
        try:
            if topic_id:
                session.post(
                    f"http://{MEP_ADDRESS}/traffic_inteligence/heartbeat",
                    json={"topic_id": topic_id},
                    timeout=2
                )
        except Exception as e:
            print(f"[UE {UE_ID}] Erro heartbeat: {e}")

        time.sleep(15)


def video_stream():
    global endpoint
    session = requests.Session()

    while True:
        try:
            with lock:
                url = endpoint + "/video"

            print(f"[UE {UE_ID}] Streaming de {url}")

            with session.get(url, stream=True, timeout=10) as r:
                start = time.time()
                bytes_received = 0

                for chunk in r.iter_content(1024):
                    if not chunk:
                        break

                    bytes_received += len(chunk)

                    if bytes_received > 1024 * 1024:
                        elapsed = time.time() - start
                        throughput = bytes_received / elapsed / 1024 / 1024
                        print(f"[UE {UE_ID}] Throughput: {throughput:.2f} MB/s")
                        bytes_received = 0
                        start = time.time()

        except Exception as e:
            print(f"[UE {UE_ID}] Erro no stream: {e}")
            time.sleep(1)


def inference_loop():
    global endpoint, topic_id
    session = requests.Session()

    while True:
        try:
            with lock:
                url = endpoint + "/infer"
                current_app = endpoint.split("/")[-1]  # pega nome do app atual

            payload = os.urandom(random.randint(500, 5000))

            start = time.time()
            headers = {"X-Work-Ms": str(PROFILE["work_ms"])} if PROFILE else None
            session.post(url, data=payload, headers=headers, timeout=2)
            latency = (time.time() - start) * 1000

            print(f"[UE {UE_ID}] Infer latency: {latency:.1f} ms")

            # 🔥 NOVO: envia latência para o Metric Catcher
            if topic_id:
                try:
                    session.post(
                        f"http://{MEP_ADDRESS}/traffic_catcher/latency",
                        json={
                            "topic": topic_id,
                            "app": current_app,
                            "latency": latency
                        },
                        timeout=1
                    )
                except Exception as e:
                    print(f"[UE {UE_ID}] Erro ao enviar latência: {e}")

        except Exception as e:
            print(f"[UE {UE_ID}] Erro infer: {e}")

        time.sleep(random.uniform(*PROFILE["interval"]) if PROFILE else random.uniform(0.1, 0.5))


if __name__ == "__main__":
    threading.Thread(target=listen_updates, daemon=True).start()
    threading.Thread(target=heartbeat_loop, daemon=True).start()

    # Fragmentar usuários entre vídeo e inferência
    threading.Thread(target=video_stream, daemon=True).start()
    threading.Thread(target=inference_loop, daemon=True).start()

    while True:
        time.sleep(10)