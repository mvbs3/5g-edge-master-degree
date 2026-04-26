import cv2
import base64
import requests
import time

URL = "http://192.168.70.2/TimeService/upload"  # Endpoint do servidor

cap = cv2.VideoCapture(0)  # Captura da webcam

while True:
    ret, frame = cap.read()
    if not ret:
        continue

    _, buffer = cv2.imencode(".jpg", frame)
    frame_base64 = base64.b64encode(buffer).decode("utf-8")

    # Envia o frame para o servidor
    try:
        requests.post(URL, json={"frame": frame_base64}, timeout=0.5)
    except requests.exceptions.RequestException as e:
        print(f"Erro ao enviar frame: {e}")

    time.sleep(0.03)  # Ajuste para controlar a taxa de envio

cap.release()
