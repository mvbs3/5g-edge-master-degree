#!/usr/bin/env bash
# ============================================================================
# Orquestrador de experimento — MAB vs Round Robin.
#
# Uso:
#   ./run_experiment.sh mab
#   ./run_experiment.sh rr
#
# Pré-requisitos:
#   1. Stack inteiro já está de pé (Core, RAN, MEP, MEC apps, intelligence,
#      catcher, mapeK). O jeito mais simples: rode automacao_script.py
#      opção 1 antes (mas SEM o trecho que dispara as UEs).
#   2. mec_app_inteligence.py precisa estar rodando com a env var
#      CONTROLLER_TYPE compatível com o cenário. Ex:
#        CONTROLLER_TYPE=mab python3 mec_app_inteligence.py
#      ou
#        CONTROLLER_TYPE=rr  python3 mec_app_inteligence.py
#      Se já estiver rodando com o controller errado, mate e reinicie.
#
# O script:
#   - limpa CSVs de saída anteriores
#   - copia run_workload.sh pra dentro do container nr_ue
#   - dispara o workload em background no container
#   - aguarda 60 min (com barra de progresso simples)
#   - mata UEs e o workload
#   - arquiva os CSVs em runs/<scenario>_<timestamp>/
#   - copia o rl_input_state.csv pra graficos/ com nome do cenário
# ============================================================================

set -euo pipefail

SCENARIO="${1:-}"
if [[ "$SCENARIO" != "mab" && "$SCENARIO" != "rr" ]]; then
    echo "Uso: $0 {mab|rr}"
    exit 1
fi

DURATION_MIN="${DURATION_MIN:-60}"
DURATION_SEC=$((DURATION_MIN * 60))

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
RUN_DIR="$PROJECT_ROOT/runs/${SCENARIO}_${RUN_TS}"
GRAFICOS_DIR="$PROJECT_ROOT/graficos"
mkdir -p "$RUN_DIR"

echo "============================================================"
echo "  EXPERIMENTO: $SCENARIO ($DURATION_MIN min)"
echo "  Saída: $RUN_DIR"
echo "============================================================"

# Sanidade: nr_ue precisa estar de pé
if ! docker ps --format '{{.Names}}' | grep -q '^nr_ue$'; then
    echo "ERRO: container 'nr_ue' não está rodando. Suba o stack antes."
    exit 1
fi

# 0. Recheck do controller que está em uso
echo
echo "ATENÇÃO: confirme que mec_app_inteligence.py foi iniciado com"
echo "         CONTROLLER_TYPE=$SCENARIO."
echo "         Aperte ENTER pra continuar ou Ctrl+C pra abortar."
read -r _

# 1. Limpa estado
echo "[1/5] Limpando CSVs anteriores..."
rm -f "$PROJECT_ROOT/mec_apps/Results/rewards.csv"
rm -f "$PROJECT_ROOT/mec_apps/Results/arm_probabilities.csv"
rm -f "$PROJECT_ROOT/mec_apps/rl_input_state.csv"

# 2. Copia workload e dispara
echo "[2/5] Disparando workload no nr_ue..."
docker cp "$PROJECT_ROOT/5g_ran/ueransim/run_workload.sh" nr_ue:/mnt/ueransim/run_workload.sh
docker exec nr_ue chmod +x /mnt/ueransim/run_workload.sh
docker exec -d nr_ue bash -c \
    "/mnt/ueransim/run_workload.sh > /mnt/ueransim/workload_${SCENARIO}_${RUN_TS}.log 2>&1"
START_TS=$(date +%s)

# 3. Espera com progresso
echo "[3/5] Aguardando $DURATION_MIN min..."
while :; do
    elapsed=$(( $(date +%s) - START_TS ))
    if (( elapsed >= DURATION_SEC )); then break; fi
    pct=$(( elapsed * 100 / DURATION_SEC ))
    printf "\r  [%3d%%] %d / %d s" "$pct" "$elapsed" "$DURATION_SEC"
    sleep 30
done
printf "\r  [100%%] %d / %d s\n" "$DURATION_SEC" "$DURATION_SEC"

# 4. Mata UEs e o workload script
echo "[4/5] Matando UEs e workload script no container..."
docker exec nr_ue pkill -f "ue_client.py" || true
docker exec nr_ue pkill -f "run_workload.sh" || true
sleep 5

# 5. Arquiva resultados
echo "[5/5] Arquivando resultados..."
if [[ -f "$PROJECT_ROOT/mec_apps/rl_input_state.csv" ]]; then
    cp "$PROJECT_ROOT/mec_apps/rl_input_state.csv" "$RUN_DIR/rl_input_state.csv"
    cp "$PROJECT_ROOT/mec_apps/rl_input_state.csv" "$GRAFICOS_DIR/rl_input_state_${SCENARIO}.csv"
else
    echo "  AVISO: rl_input_state.csv não foi gerado — verifique mec_app_inteligence."
fi
cp -r "$PROJECT_ROOT/mec_apps/Results" "$RUN_DIR/Results" 2>/dev/null || true
docker cp "nr_ue:/mnt/ueransim/workload_${SCENARIO}_${RUN_TS}.log" "$RUN_DIR/" 2>/dev/null || true

echo "============================================================"
echo "  Experimento $SCENARIO finalizado."
echo "  Resultado:        $RUN_DIR"
echo "  CSV pra gráficos: $GRAFICOS_DIR/rl_input_state_${SCENARIO}.csv"
echo
echo "  Próximos passos:"
echo "    - Rode o outro cenário (mab ou rr)"
echo "    - Quando tiver os 2 CSVs, gere os gráficos:"
echo "        cd $GRAFICOS_DIR && python3 graficos_compare.py"
echo "============================================================"
