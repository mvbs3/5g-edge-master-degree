#!/bin/bash

# Parâmetros
NAME=$1
PORT=$2
PY_FILE=$3
MEC_NAME=$4
MEC_HOST=${5:-127.0.0.1}
MEC_APP="app.py"
IMAGE="mec_app:latest"
NETWORK="demo-oai-public-net"

# Validação
if [ -z "$NAME" ] || [ -z "$PORT" ] || [ -z "$PY_FILE" ] || [ -z "$MEC_NAME" ]; then
  echo "❌ Uso: $0 <nome_container> <porta> <arquivo.py> <mec_name> [mec_host]"
  exit 1
fi

# Caminho absoluto do script Python
PY_ABS_PATH=$(realpath "$PY_FILE")

echo "🚀 Iniciando container '$NAME' com app '$PY_FILE' na porta $PORT e MEC_NAME='$MEC_NAME'..."

docker run -d \
  --name "$NAME" \
  -v "$PY_ABS_PATH":/app/app.py \
  -e "MEC_NAME=$MEC_NAME" \
  -e "MEC_PORT=$PORT" \
  -e "MEC_HOST=$MEC_HOST" \
  -e "MEC_APP=$MEC_APP" \
  -p "$PORT:$PORT" \
  --network "$NETWORK" \
  "$IMAGE" 
echo "📜 Logs do container '$NAME':"
docker logs -f "$NAME"
