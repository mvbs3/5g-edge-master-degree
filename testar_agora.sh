#!/usr/bin/env bash
# ============================================================================
# UM COMANDO: sobe o stack, roda o cenário e analisa o resultado.
#
#   ./testar_agora.sh mab              → cenário curto de validação (~13 min, 10→40 UEs)
#   ./testar_agora.sh rr
#   ./testar_agora.sh mab completo     → experimento do paper (~60 min, 10→100 UEs)
#   ./testar_agora.sh rr completo
#   ./testar_agora.sh mab_lat [completo] → MAPE-K por latência + UEs leve/médio/pesado
#   ./testar_agora.sh rr_lat  [completo]
#
# Existe porque a opção 1 do automacao_script.py, além de subir o stack, dispara
# 100 UEs fixas no fim — se elas ficarem vivas, somam com as 10→40 do cenário
# curto e o teste não mede nada. Aqui o stack sobe, as UEs avulsas são mortas, e
# só então o workload com fases roda.
#
# Pula o que já está de pé: pode rodar de novo sem derrubar nada.
#
# Opções:
#   PULAR_SETUP=1 ./testar_agora.sh mab   → stack já está pronto, só roda o teste
# ============================================================================

set -euo pipefail

CENARIO="${1:-}"
MODO="${2:-curto}"
case "$CENARIO" in mab|rr|mab_lat|rr_lat) ;; *) CENARIO="" ;; esac
if [[ -z "$CENARIO" ]] || [[ "$MODO" != "curto" && "$MODO" != "completo" ]]; then
    echo "Uso: $0 {mab|rr|mab_lat|rr_lat} [completo]"
    exit 1
fi

# mab/rr: MAPE-K por CPU, UEs uniformes (experimento original, intocado).
# mab_lat/rr_lat: MAPE-K por latência, UEs com perfis leve/médio/pesado
# (LOAD_PROFILE é aplicado pelo run_experiment.sh). O roteador é o mesmo nos dois.
CONTROLLER="${CENARIO%_lat}"
if [[ "$CENARIO" == *_lat ]]; then SCALING_METRIC=latency; else SCALING_METRIC=cpu; fi

RAIZ="$(cd "$(dirname "$0")" && pwd)"
cd "$RAIZ"

passo() { echo; echo "=============== $* ==============="; }
no_ar() { docker ps --format '{{.Names}}' | grep -qx "$1"; }

# Aviso sonoro: N bipes curtos. O principal é o bell do terminal (\a), que atravessa o
# SSH e o tmux e toca no PC de quem está conectado. Se o server tiver áudio, toca
# também por lá. Vai direto pro /dev/tty porque o stdout costuma estar num `| tee`.
#   2 bipes = experimento começou   3 bipes = acabou (com sucesso ou erro)
bipe() {
    local n="$1" som=/usr/share/sounds/freedesktop/stereo/complete.oga
    for _ in $(seq 1 "$n"); do
        { printf '\a' > /dev/tty; } 2>/dev/null || printf '\a'
        if command -v paplay >/dev/null 2>&1 && [[ -f "$som" ]]; then
            paplay "$som" >/dev/null 2>&1 &
        fi
        sleep 0.4
    done
}
# Dispara em qualquer saída — fim normal, erro do set -e ou Ctrl+C —, então o som de
# fim toca mesmo se o cenário quebrar no setup.
fim_do_cenario() {
    local status=$?
    if [[ "$status" == "0" ]]; then
        echo; echo ">>> [$(date +%H:%M:%S)] CENÁRIO $CENARIO TERMINOU — pode rodar o próximo"
    else
        echo; echo ">>> [$(date +%H:%M:%S)] CENÁRIO $CENARIO PAROU COM ERRO (código $status) — veja acima"
    fi
    bipe 3
}
trap fim_do_cenario EXIT

# ---------------------------------------------------------------- 1. stack
# O automacao_script.py NÃO serve aqui: ele roda `docker-compose up` anexado
# (sem -d, automacao_script.py:208), então sair do menu com Ctrl+C derruba os
# composes junto — foi o que fez o nr_ue sumir entre uma checagem e outra. E sair
# com 'q' chama o shutdown geral. Subimos os composes direto, em modo detached.
subir_compose() {
    local arquivo="$1" dir="$2" nome="$3"
    echo "  subindo $nome..."
    (cd "$RAIZ/$dir" && docker-compose -f "$arquivo" up -d) >/dev/null 2>&1 || {
        echo "  ERRO ao subir $nome — rode à mão pra ver o erro:"
        echo "    cd $RAIZ/$dir && docker-compose -f $arquivo up -d"
        return 1
    }
}

if [[ "${PULAR_SETUP:-0}" == "1" ]]; then
    passo "SETUP PULADO (PULAR_SETUP=1)"
elif no_ar nr_ue; then
    passo "STACK JÁ ESTÁ DE PÉ — pulando setup"
else
    passo "SUBINDO O STACK (detached, sem o menu interativo)"
    # Nomes e diretórios vêm do DockerConfig do automacao_script.py (linhas 44-50),
    # na mesma ordem em que a opção 1 os sobe.
    subir_compose sa-deploy.yaml          5g_core "Core (Open5GS)"
    sleep 20
    subir_compose docker-compose-ran.yaml 5g_ran  "RAN (gNB)"
    sleep 10
    subir_compose docker-compose-cm.yaml  5g_mep  "Config Manager"
    sleep 5
    subir_compose docker-compose-mep.yaml 5g_mep  "MEP"
    sleep 10
    subir_compose docker-compose-nrue.yaml 5g_ran "UE (nr_ue)"
    sleep 5

    if ! no_ar nr_ue; then
        echo
        echo "ERRO: nr_ue não subiu. Veja o que falhou com:"
        echo "  cd $RAIZ/5g_ran && docker-compose -f docker-compose-nrue.yaml up"
        exit 1
    fi
    echo "  stack no ar"
fi

# ------------------------------------------- 1a. pool MEC recriado do zero
# Roda em TODO cenário, mesmo com o stack de pé. O reset_vidproc_pool do
# run_experiment.sh só mata as instâncias >= 2; a 0 e a 1 sobreviviam de um cenário
# pro outro com metrics/latency_samples/frame_buffer em memória, e se um cenário
# quebrasse no meio as extras dele também sobravam. Aqui todas são desregistradas e
# removidas, e a 0 e a 1 sobem limpas — os cenários partem exatamente do mesmo estado.
passo "RECRIANDO O POOL MEC (todas as instâncias removidas, 0 e 1 sobem limpas)"
# O mec_instance_manager.py precisa de requests/dotenv, que vivem no venv dos mec_apps.
# shellcheck disable=SC1091
[[ -f "$RAIZ/mec_apps/mec_app1/bin/activate" ]] && source "$RAIZ/mec_apps/mec_app1/bin/activate"
for container in $(docker ps -a --format '{{.Names}}' | grep -E '^mec_app1_instance[0-9]+$' || true); do
    index="${container#mec_app1_instance}"
    echo "  removendo $container (VideoStreamingService${index})"
    python3 "$RAIZ/mec_instance_manager.py" stop "$container" \
        --mec_name "VideoStreamingService${index}" >/dev/null 2>&1 || \
        echo "    AVISO: falha ao desregistrar $container"
    docker rm -f "$container" >/dev/null 2>&1 || true
done
sleep 3

# Não dá pra usar `mec_instance_manager.py start`: ele termina chamando
# show_logs(), que é um `docker logs -f` e nunca retorna (mec_instance_manager.py:115).
# O automacao_script.py não trava nisso porque abre cada instância num terminal
# próprio; aqui seria o fim do script. Então replicamos o docker run dele.
IP_LOCAL="$(hostname -I | awk '{print $1}')"
for i in 0 1; do
    if docker run -d --name "mec_app1_instance$i" \
        -v "$RAIZ/examples/mec_app1.py:/app/app.py" \
        -v "$RAIZ/uploads:/app/uploads" \
        -e "MEC_NAME=VideoStreamingService$i" \
        -e "MEC_PORT=$((8090 + i))" \
        -e "MEC_HOST=$IP_LOCAL" \
        -e MEC_APP=app.py \
        -p "$((8090 + i)):$((8090 + i))" \
        --network docker_open5gs_default \
        --memory 512m --memory-reservation 256m --cpus 0.20 \
        --add-host host.docker.internal:host-gateway \
        mec_app:latest >/dev/null; then
        echo "  mec_app1_instance$i no ar (porta $((8090 + i)))"
    else
        echo "  ERRO ao subir mec_app1_instance$i"
        exit 1
    fi
    sleep 3
done

echo "  aguardando as instâncias se registrarem no service_registry..."
sleep 10

# ------------------------------------------- 1b. Prometheus + cAdvisor
# O catcher tira a CPU das instâncias do Prometheus (mec_app_metric_catcher.py:16),
# que lê do cAdvisor. A opção 1 do menu subia os dois via start_prometheus_grafana()
# (automacao_script.py:213) antes do core; sem eles toda CPU vira N/A e o mapeK
# decide NO_ACTION o teste inteiro. Roda mesmo com PULAR_SETUP=1.
# Mesmo host que o catcher consulta: MEC_HOST do mec_apps/.env.
PROM_HOST="$(grep -s '^MEC_HOST=' "$RAIZ/mec_apps/.env" | cut -d= -f2 || true)"
PROM_HOST="${PROM_HOST:-$(hostname -I | awk '{print $1}')}"
PROM_URL="http://${PROM_HOST}:9090"
passo "PROMETHEUS ($PROM_URL)"
if curl -s --max-time 5 "$PROM_URL/-/ready" >/dev/null; then
    echo "  já está no ar"
else
    # O menu encadeia `docker swarm init && ...`: se o nó já é swarm o init falha e o
    # deploy nunca roda. Aqui só inicia o swarm quando ele não está ativo.
    if [[ "$(docker info --format '{{.Swarm.LocalNodeState}}')" != "active" ]]; then
        docker swarm init --advertise-addr "$PROM_HOST" >/dev/null
    fi
    (cd "$RAIZ/prometheus" && HOSTNAME=$(hostname) docker stack deploy -c docker-stack.yml prom) >/dev/null
    echo -n "  aguardando o Prometheus responder"
    for _ in $(seq 1 30); do
        curl -s --max-time 2 "$PROM_URL/-/ready" >/dev/null && break
        echo -n "."
        sleep 2
    done
    echo
fi

# O rate()[1m] precisa de ~2 scrapes do cAdvisor antes de devolver algo.
echo -n "  aguardando CPU de mec_app1_instance0 no Prometheus"
cpu_ok=0
for _ in $(seq 1 30); do
    if curl -s --max-time 5 "$PROM_URL/api/v1/query" \
        --data-urlencode 'query=rate(container_cpu_usage_seconds_total{name="mec_app1_instance0"}[1m])' \
        | grep -q '"value"'; then
        cpu_ok=1
        break
    fi
    echo -n "."
    sleep 5
done
echo
if [[ "$cpu_ok" != "1" ]]; then
    echo "  ERRO: o Prometheus não devolve CPU das instâncias MEC — o teste não mediria nada."
    echo "  Confira: docker stack ps prom   e   curl $PROM_URL/api/v1/targets"
    exit 1
fi
echo "  CPU das instâncias chegando"

# ------------------------------------------------- 2. matar UEs avulsas
# A opção 1 sobe 100 UEs direto, sem fases. Elas precisam morrer: o cenário curto
# é quem controla a carga, e 100 UEs fixas por cima mascaram todo o resultado.
passo "LIMPANDO UEs AVULSAS"
vivas=$( (docker exec nr_ue pgrep -f ue_client.py 2>/dev/null || true) | wc -l | tr -d ' ')
if [[ "$vivas" != "0" ]]; then
    echo "  $vivas UE(s) rodando fora do workload — matando"
    docker exec nr_ue pkill -f ue_client.py || true
    sleep 3
fi
echo "  UEs vivas agora: $(docker exec nr_ue pgrep -f ue_client.py 2>/dev/null | wc -l | tr -d ' ')"

# ------------------------------------------- 2b. Redis visível de dentro do nr_ue
# A inteligência publica a escolha do MAB/RR no Redis e cada UE escuta seu topic
# (ue_client.py:33, host = MEC_HOST). Se o nr_ue não alcança o Redis, a thread de
# escuta morre no boot e TODAS as UEs ficam no endpoint inicial (VideoStreamingService0):
# o roteador decide, ninguém obedece, e a comparação MAB x RR não mede nada.
passo "REDIS ($PROM_HOST:6379, visto de dentro do nr_ue)"
redis_ok() {
    docker exec nr_ue python3 -c "import redis; redis.Redis(host='$PROM_HOST', port=6379, socket_connect_timeout=3).ping()" >/dev/null 2>&1
}
if ! redis_ok; then
    # Nenhum compose sobe o Redis. Publica só no loopback (a inteligência usa
    # 127.0.0.1, mec_app_inteligence.py:634) e no IP que as UEs usam, nada além.
    echo "  Redis fora do ar — subindo o container 'redis'"
    docker rm -f redis >/dev/null 2>&1 || true
    docker run -d --name redis --restart unless-stopped \
        -p "127.0.0.1:6379:6379" -p "$PROM_HOST:6379:6379" \
        redis:7 >/dev/null || true
    sleep 3
fi
if redis_ok; then
    echo "  nr_ue alcança o Redis"
else
    echo "  ERRO: o nr_ue não alcança o Redis em $PROM_HOST:6379."
    echo "  Confira: docker logs redis   e   sudo ss -ltnp | grep 6379"
    echo "  (um redis-server do sistema na 6379 ouvindo só em 127.0.0.1 impede o container de subir)"
    exit 1
fi

# --------------------------------------- 3. inteligência com o controller certo
# Precisa reiniciar de todo jeito: a opção 1 sobe sem CONTROLLER_TYPE, e a versão
# em execução pode ser a anterior às correções (sem cpu_avg_percent, o que faz o
# mapeK cair no fallback e o scale-down nunca acontecer).
passo "REINICIANDO INTELIGÊNCIA (CONTROLLER_TYPE=$CONTROLLER) E MAPE-K (SCALING_METRIC=$SCALING_METRIC)"
pkill -f mec_app_inteligence.py 2>/dev/null || true
pkill -f mapeK.py 2>/dev/null || true
pkill -f mec_app_metric_catcher.py 2>/dev/null || true
sleep 3

mkdir -p logs
cd mec_apps
# shellcheck disable=SC1091
[[ -f mec_app1/bin/activate ]] && source mec_app1/bin/activate

# O catcher vem primeiro: é ele que recebe /latency e /app_metrics das instâncias.
# Sem ele não há métrica de CPU, o mapeK decide NO_ACTION pra sempre e o teste não
# mede nada. A opção 1 do menu o subia; como não usamos mais o menu, sobe aqui.
nohup python3 mec_app_metric_catcher.py > "$RAIZ/logs/catcher_${CENARIO}.log" 2>&1 &
echo "  catcher iniciado (log: logs/catcher_${CENARIO}.log)"
sleep 10

CONTROLLER_TYPE="$CONTROLLER" nohup python3 mec_app_inteligence.py \
    > "$RAIZ/logs/inteligencia_${CENARIO}.log" 2>&1 &
echo "  inteligência iniciada (log: logs/inteligencia_${CENARIO}.log)"
sleep 15

# O mapeK só sobe depois: ele lê o endpoint da inteligência no primeiro ciclo.
SCALING_METRIC="$SCALING_METRIC" nohup python3 mapeK.py > "$RAIZ/logs/mapek_${CENARIO}.log" 2>&1 &
echo "  mapeK iniciado (log: logs/mapek_${CENARIO}.log)"
cd "$RAIZ"
sleep 5

# Confere que os campos novos estão no ar — sem eles o teste não prova nada
passo "CONFERINDO O ENDPOINT DE CPU"
# A inteligência usa 192.168.70.2 por default e o mapeK usa 172.22.0.162
# (mec_app_inteligence.py:63 vs mapeK.py:36). Tenta os dois: na execução anterior a
# resposta veio vazia justamente porque só o endereço do mapeK foi consultado.
resposta=""
for MEP in "${MEP_ADDRESS:-}" 192.168.70.2 172.22.0.162; do
    [[ -z "$MEP" ]] && continue
    resposta=$(curl -s --max-time 5 "http://${MEP}/traffic_inteligence/cpu_percent" || true)
    if [[ -n "$resposta" ]]; then
        echo "  [$MEP] $resposta"
        break
    fi
    echo "  [$MEP] sem resposta"
done
if [[ "$resposta" != *"cpu_avg_percent"* ]]; then
    echo
    echo "  AVISO: 'cpu_avg_percent' não apareceu na resposta."
    echo "  A inteligência em execução é a versão ANTIGA — o mapeK vai usar o max"
    echo "  nos dois lados e o scale-down não vai acontecer. Confira se o pull das"
    echo "  correções chegou neste server antes de confiar no resultado."
    bipe 1  # parado esperando Enter
    read -r -p "  Enter para continuar mesmo assim, Ctrl+C para abortar..." _
fi

# Sem /latency_stats o mapeK dos cenários *_lat lê N/A pra sempre e nunca escala.
if [[ "$SCALING_METRIC" == "latency" ]]; then
    passo "CONFERINDO O ENDPOINT DE LATÊNCIA"
    lat=$(curl -s --max-time 5 "http://${MEP}/traffic_inteligence/latency_stats" || true)
    echo "  [$MEP] $lat"
    if [[ "$lat" != *"max_service_avg_ms"* ]]; then
        echo "  ERRO: /latency_stats não respondeu — a inteligência em execução é anterior"
        echo "  aos cenários *_lat. Confira se o pull chegou neste server."
        exit 1
    fi
fi

# ------------------------------------------------------------ 4. o teste
# O completo usa o run_experiment.sh sem overrides (fases default do run_workload.sh)
# e grava graficos/rl_input_state_<cenario>.csv, que é o que o graficos_compare.py lê.
echo; echo ">>> [$(date +%H:%M:%S)] CENÁRIO $CENARIO COMEÇOU ($MODO)"
bipe 2
if [[ "$MODO" == "completo" ]]; then
    passo "RODANDO O EXPERIMENTO COMPLETO (~60 min, 10→100 UEs)"
    AUTO_CONFIRM=1 ./run_experiment.sh "$CENARIO"
    CSV="graficos/rl_input_state_${CENARIO}.csv"
    RUNS_GLOB="runs/${CENARIO}_2*"
    ANALISE_ARGS=()
else
    passo "RODANDO O CENÁRIO CURTO (~13 min)"
    AUTO_CONFIRM=1 ./run_experiment_short.sh "$CENARIO"
    CSV="graficos/rl_input_state_${CENARIO}_short.csv"
    RUNS_GLOB="runs/${CENARIO}_short_*"
    ANALISE_ARGS=()
fi

# ---------------------------------------------------------- 5. veredito
passo "ANALISANDO"
if [[ -f "$CSV" ]]; then
    python3 analisa_execucao.py "$CSV" ${ANALISE_ARGS[@]+"${ANALISE_ARGS[@]}"} || true
else
    echo "ERRO: $CSV não foi gerado — veja os avisos do run_experiment.sh acima."
fi

passo "ARQUIVOS PRA MANDAR PARA ANÁLISE"
echo "  $CSV"
ls -td $RUNS_GLOB 2>/dev/null | head -1 | sed 's/^/  /' || true
echo "  logs/mapek_${CENARIO}.log"
