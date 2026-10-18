#!/usr/bin/env bash
# ============================================================================
# UM COMANDO: sobe o stack, roda o cenário curto e analisa o resultado.
#
#   ./testar_agora.sh mab
#   ./testar_agora.sh rr
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
if [[ "$CENARIO" != "mab" && "$CENARIO" != "rr" ]]; then
    echo "Uso: $0 {mab|rr}"
    exit 1
fi

RAIZ="$(cd "$(dirname "$0")" && pwd)"
cd "$RAIZ"

passo() { echo; echo "=============== $* ==============="; }
no_ar() { docker ps --format '{{.Names}}' | grep -qx "$1"; }

# ---------------------------------------------------------------- 1. stack
if [[ "${PULAR_SETUP:-0}" == "1" ]]; then
    passo "SETUP PULADO (PULAR_SETUP=1)"
elif no_ar nr_ue; then
    passo "STACK JÁ ESTÁ DE PÉ — pulando setup"
else
    passo "SUBINDO O STACK"
    echo "Isso abre vários terminais e leva alguns minutos."
    echo "No menu, escolha 1 e aguarde ate aparecer 'Ues iniciadas com sucesso'."
    echo "Entao saia com Ctrl+C -- NAO use 'q', que derruba o stack inteiro."
    echo
    read -r -p "Enter para abrir o automacao_script.py..." _
    python3 automacao_script.py || true

    if ! no_ar nr_ue; then
        echo "ERRO: o container nr_ue continua fora do ar. O setup falhou."
        exit 1
    fi
fi

# ------------------------------------------------- 2. matar UEs avulsas
# A opção 1 sobe 100 UEs direto, sem fases. Elas precisam morrer: o cenário curto
# é quem controla a carga, e 100 UEs fixas por cima mascaram todo o resultado.
passo "LIMPANDO UEs AVULSAS"
vivas=$(docker exec nr_ue pgrep -f ue_client.py 2>/dev/null | wc -l | tr -d ' ')
if [[ "$vivas" != "0" ]]; then
    echo "  $vivas UE(s) rodando fora do workload — matando"
    docker exec nr_ue pkill -f ue_client.py || true
    sleep 3
fi
echo "  UEs vivas agora: $(docker exec nr_ue pgrep -f ue_client.py 2>/dev/null | wc -l | tr -d ' ')"

# --------------------------------------- 3. inteligência com o controller certo
# Precisa reiniciar de todo jeito: a opção 1 sobe sem CONTROLLER_TYPE, e a versão
# em execução pode ser a anterior às correções (sem cpu_avg_percent, o que faz o
# mapeK cair no fallback e o scale-down nunca acontecer).
passo "REINICIANDO INTELIGÊNCIA (CONTROLLER_TYPE=$CENARIO) E MAPE-K"
pkill -f mec_app_inteligence.py 2>/dev/null || true
pkill -f mapeK.py 2>/dev/null || true
sleep 3

mkdir -p logs
cd mec_apps
# shellcheck disable=SC1091
[[ -f mec_app1/bin/activate ]] && source mec_app1/bin/activate
CONTROLLER_TYPE="$CENARIO" nohup python3 mec_app_inteligence.py \
    > "$RAIZ/logs/inteligencia_${CENARIO}.log" 2>&1 &
echo "  inteligência iniciada (log: logs/inteligencia_${CENARIO}.log)"
sleep 15

# O mapeK só sobe depois: ele lê o endpoint da inteligência no primeiro ciclo.
nohup python3 mapeK.py > "$RAIZ/logs/mapek_${CENARIO}.log" 2>&1 &
echo "  mapeK iniciado (log: logs/mapek_${CENARIO}.log)"
cd "$RAIZ"
sleep 5

# Confere que os campos novos estão no ar — sem eles o teste não prova nada
passo "CONFERINDO O ENDPOINT DE CPU"
MEP="${MEP_ADDRESS:-172.22.0.162}"
resposta=$(curl -s --max-time 10 "http://${MEP}/traffic_inteligence/cpu_percent" || true)
echo "  $resposta"
if [[ "$resposta" != *"cpu_avg_percent"* ]]; then
    echo
    echo "  AVISO: 'cpu_avg_percent' não apareceu na resposta."
    echo "  A inteligência em execução é a versão ANTIGA — o mapeK vai usar o max"
    echo "  nos dois lados e o scale-down não vai acontecer. Confira se o pull das"
    echo "  correções chegou neste server antes de confiar no resultado."
    read -r -p "  Enter para continuar mesmo assim, Ctrl+C para abortar..." _
fi

# ------------------------------------------------------------ 4. o teste
passo "RODANDO O CENÁRIO CURTO (~13 min)"
AUTO_CONFIRM=1 ./run_experiment_short.sh "$CENARIO"

# ---------------------------------------------------------- 5. veredito
passo "ANALISANDO"
CSV="graficos/rl_input_state_${CENARIO}_short.csv"
if [[ -f "$CSV" ]]; then
    python3 analisa_execucao.py "$CSV" || true
else
    echo "ERRO: $CSV não foi gerado — veja os avisos do run_experiment.sh acima."
fi

passo "ARQUIVOS PRA MANDAR PARA ANÁLISE"
echo "  $CSV"
ls -t runs/${CENARIO}_short_*/workload_*.log 2>/dev/null | head -1 | sed 's/^/  /' || true
echo "  logs/mapek_${CENARIO}.log"
