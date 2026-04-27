from flask import Flask, jsonify, request, Response
import os
import requests
import datetime
import threading
import cv2
import base64
import numpy as np
import psutil
import subprocess
import time
import json
from collections import deque
import ipfshttpclient

MEC_NAME = os.getenv("MEC_NAME", "TimeService")
MEC_PORT = int(os.getenv("MEC_PORT", 8080))
MEC_HOST = os.getenv("MEC_HOST", "1150.161.121.210")
MEP_ADDRESS = os.getenv("MEP_ADDRESS", "172.22.0.162")

MAX_FRAMES_BUFFER = int(os.getenv("MAX_FRAMES_BUFFER", 5))

def get_container_id():
    try:
        # Usando o comando Docker para pegar o nome do container
        container_name = subprocess.check_output("hostname", shell=True).strip().decode("utf-8")
        return container_name
    except Exception as e:
        print(f"Erro ao tentar obter o nome do container: {e}")
        return None

metrics = {
    "active_requests": 0,
    "frames_received": 0,
    "frames_dropped": 0,
    "frames_sent": 0,
    "current_fps": 0,
    "avg_latency_ms": 0,
    "throughput_kbps": 0,
    "container_id": get_container_id()
}

metrics["active_requests"] = 0
buffer_lock = threading.Lock()
metrics_lock = threading.Lock()
req_lock = threading.Lock()
lock = threading.Lock()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

frame_buffer = deque(maxlen=MAX_FRAMES_BUFFER)
latency_samples = deque(maxlen=100)  # Store last 100 latency samples

#latest_frame = None
def register_mec():
    mec_data = {
        "description": "Video Streaming Service with real-time metrics",
        "endpoints": [
            {
                "description": "Streams live video feed",
                "method": "GET",
                "name": "video_feed",
                "parameters": [],
                "path": "/video"
            },
            {
                "description": "Uploads a video frame",
                "method": "POST",
                "name": "upload_frame",
                "parameters": [],
                "path": "/upload"
            },
            {
                "description": "Uploads a file to the service",
                "method": "POST",
                "name": "upload_file",
                "parameters": [],
                "path": "/upload_file"
            },
            {
                "description": "Returns system and streaming metrics",
                "method": "GET",
                "name": "get_metrics",
                "parameters": [],
                "path": "/metric"
            },
            {
                "description": "Simple hello world endpoint",
                "method": "GET",
                "name": "get_hello",
                "parameters": [],
                "path": "/hello-api"
            }
        ],
        "host": MEC_HOST,
        "name": MEC_NAME,
        "path": "/apiFlask/v1",
        "port": MEC_PORT,
        "sid": f'{MEC_NAME}-sid',
        "type": "VidProc",
        "uid": f'{MEC_NAME}-uid'
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

@app.before_request
def before_request():
    global metrics
    with metrics_lock:
        metrics["active_requests"] += 1

@app.after_request
def after_request(response):
    global metrics
    with metrics_lock   :
        metrics["active_requests"] -= 1
    return response

@app.route("/video", methods=["GET"])
def video_feed():
    def generate():
        client_id = f"client-{int(time.time() * 1000)}"
        print(f"New client connected: {client_id}")
        last_frame_id = None
        
        while True:
            frame_data = None
            
            # Get the latest frame with minimal locking time
            with buffer_lock:
                if frame_buffer:
                    frame_data = frame_buffer[-1]  # Get the newest frame
            
            if not frame_data:
                # No frame available, send a small delay
                time.sleep(0.01)
                continue
                
            frame, frame_id, timestamp = frame_data
            
            # Check if this is a new frame for this client
            if last_frame_id != frame_id:
                last_frame_id = frame_id
                
                # Calculate latency and add to metrics
                latency_ms = (time.time() - timestamp) * 1000
                latency_samples.append(latency_ms)
                
                # Encode the frame
                _, buffer = cv2.imencode(".jpg", frame)
                frame_bytes = buffer.tobytes()
                
                # Increment frames sent counter
                with metrics_lock:
                    metrics["frames_sent"] += 1
                
                timestamp_now = time.time()

                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"X-Timestamp: " + str(timestamp_now).encode() + b"\r\n\r\n" +
                    frame_bytes +
                    b"\r\n"
                )
            else:
                # This client already saw this frame, small wait
                time.sleep(0.01)

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/upload", methods=["POST"])
def upload_frame():
    try:
        # Get the frame data
        data = request.json
        receive_timestamp = time.time()
        frame_timestamp = data.get("timestamp")
        img_data = base64.b64decode(data["frame"])
        np_arr = np.frombuffer(img_data, dtype=np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

        if frame is None:
            return "Invalid frame", 400

        # Generate a unique frame ID
        frame_id = int(time.time() * 1000)
        
        # Get current time for latency calculation
        timestamp = time.time()
        
        # Update the frame buffer with the new frame
        with buffer_lock:
            # If buffer is full, we're dropping frames
            if len(frame_buffer) == MAX_FRAMES_BUFFER:
                with metrics_lock:
                    metrics["frames_dropped"] += 1
            
            # Add the new frame to the buffer
            frame_buffer.append((frame, frame_id, timestamp))
            
            # Update metrics
            with metrics_lock:
                metrics["frames_received"] += 1

        return "Frame received", 200
    except Exception as e:
        return f"Error: {e}", 400
import hashlib

@app.route('/upload_file', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'Nenhum arquivo enviado'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'error': 'Nome do arquivo vazio'}), 400

    # Salva o arquivo
    file_path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(file_path)

    # --- Gerar hash SHA-256 ---
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        # Lê o arquivo em blocos pra arquivos grandes
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    file_hash = sha256_hash.hexdigest()  # hash em hexadecimal

    # Retorna info pro usuário
    return jsonify({
        'message': 'Imagem recebida com sucesso!',
        'file_path': os.path.abspath(file_path),
        'sha256': file_hash
    })

@app.route('/hello-api', methods=['GET'])
def get_time():
    return "Hello World"

@app.route('/metric', methods=['GET'])
def get_metric():

    cpu_percent = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory()
    memory_used_mb = mem.used / (1024 ** 2)
    memory_total_mb = mem.total / (1024 ** 2)
    
    system_metrics = {
        "running_in": "host",
        "cpu_percent": round(cpu_percent, 2),
        "memory_percent": round(mem.percent, 2),
        "memory_used_mb": round(memory_used_mb, 2),
        "memory_total_mb": round(memory_total_mb, 2)    }


    with metrics_lock:
        response_metrics = {
            **system_metrics,
            "container_id": metrics["container_id"],
            "active_requests": metrics["active_requests"],
            "frames_received": metrics["frames_received"],
            "frames_dropped": metrics["frames_dropped"],
            "frames_sent": metrics["frames_sent"],
            "current_fps": metrics["current_fps"],
            "avg_latency_ms": metrics["avg_latency_ms"],
            "throughput_kbps": metrics["throughput_kbps"],
            "drop_rate_percent": 0
        }
        return jsonify(response_metrics)
@app.route('/cadastrar-usuario', methods=['POST'])
def cadastrar_usuario():
    try:
        # --- Pegar dados JSON do campo "dados" ---
        if "dados" not in request.form:
            return jsonify({"error": "Campo 'dados' é obrigatório"}), 400

        try:
            usuario = json.loads(request.form["dados"])
        except Exception as e:
            return jsonify({"error": f"Erro ao processar JSON: {str(e)}"}), 400

        # --- Pegar imagem do campo "foto" ---
        if "foto" not in request.files:
            return jsonify({"error": "Campo 'foto' é obrigatório"}), 400

        foto = request.files["foto"]
        if foto.filename == "":
            return jsonify({"error": "Nome da foto inválido"}), 400

        # Salvar a imagem
        filename = os.path.basename(foto.filename)
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        foto.save(file_path)

        # --- Gerar hash SHA-256 da foto ---
        import hashlib
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        foto_hash = sha256_hash.hexdigest()
        res = ipfs_add(file_path)
        cid = res.get("Hash")

        return jsonify({
            "message": "Usuário cadastrado com sucesso!",
            "usuario": usuario,
            "foto_path": os.path.abspath(file_path),
            "foto_hash": foto_hash,
            "cid": cid,
            "ipfs_gateway": f"https://ipfs.io/ipfs/{cid}" if cid else None
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
from flask import send_file
import io

@app.route('/get_image/<cid>', methods=['GET'])
def get_image(cid):
    try:
        # Monta a URL do gateway local do IPFS
        url = f"http://host.docker.internal:8081/ipfs/{cid}"

        # Faz download da imagem
        res = requests.get(url)
        if res.status_code != 200:
            return jsonify({'error': f"Falha ao buscar imagem: {res.status_code}"}), 404

        # Retorna o conteúdo da imagem
        return send_file(
            io.BytesIO(res.content),
            mimetype=res.headers.get("Content-Type", "image/png"),
            as_attachment=False
        )

    except Exception as e:
        return jsonify({'error': str(e)}), 500
import requests

def ipfs_add(file_path):
    url = "http://host.docker.internal:5001/api/v0/add"
    with open(file_path, "rb") as f:
        files = {"file": f}
        res = requests.post(url, files=files)
    return res.json()

if __name__ == "__main__":
    container_id = get_container_id()
    print(f"Starting Video Streaming Service")
    print(f"Container ID: {container_id}")
    print(f"Maximum frames buffer: {MAX_FRAMES_BUFFER}")
    app.run(host="0.0.0.0", port=MEC_PORT, threaded=True)
