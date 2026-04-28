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

lock = threading.Lock()
topic_id = None


def listen_updates():
    global endpoint, topic_id

    r = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)
    pubsub = r.pubsub()

    response = requests.get(
        f"http://{MEP_ADDRESS}/traffic_inteligence/subscribe",
        json={"app_type": APP_TYPE},
        timeout=5
    )
    response.raise_for_status()

    topic_id = response.text.strip()
    pubsub.subscribe(topic_id)

    print(f"[UE {UE_ID}] Inscrito no topic: {topic_id}")

    for message in pubsub.listen():
        if message["type"] != "message":
            continue

        service_name = message["data"]

        with lock:
            endpoint = f"http://{MEP_ADDRESS}/{service_name}"
            print(f"[UE {UE_ID}] Novo endpoint: {endpoint}")


def heartbeat_loop():
    global topic_id

    while True:
        try:
            if topic_id:
                requests.post(
                    f"http://{MEP_ADDRESS}/traffic_inteligence/heartbeat",
                    json={"topic_id": topic_id},
                    timeout=2
                )
        except Exception as e:
            print(f"[UE {UE_ID}] Erro heartbeat: {e}")

        time.sleep(15)


def video_stream():
    global endpoint

    while True:
        try:
            with lock:
                url = endpoint + "/video"

            print(f"[UE {UE_ID}] Streaming de {url}")

            r = requests.get(url, stream=True, timeout=10)

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
    global endpoint

    while True:
        try:
            with lock:
                url = endpoint + "/infer"

            payload = os.urandom(random.randint(500, 5000))

            start = time.time()
            requests.post(url, data=payload, timeout=2)
            latency = (time.time() - start) * 1000

            print(f"[UE {UE_ID}] Infer latency: {latency:.1f} ms")

        except Exception as e:
            print(f"[UE {UE_ID}] Erro infer: {e}")

        time.sleep(random.uniform(0.1, 0.5))


if __name__ == "__main__":
    threading.Thread(target=listen_updates, daemon=True).start()
    threading.Thread(target=heartbeat_loop, daemon=True).start()

    # Fragmentar usuários entre vídeo e inferência
    threading.Thread(target=video_stream, daemon=True).start()
    threading.Thread(target=inference_loop, daemon=True).start()

    while True:
        time.sleep(10)