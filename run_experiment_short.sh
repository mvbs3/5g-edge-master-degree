#!/usr/bin/env bash
# ============================================================================
# Cenário CURTO de validação — não é experimento, é teste de fumaça.
#
# Uso:
#   ./run_experiment_short.sh mab
#   ./run_experiment_short.sh rr
#
# Para que serve:
#   Confirmar, em ~7 min em vez de 60, que o ciclo de vida está correto:
#     - as UEs sobem, e DESCEM de volta ao valor de warmup no drain
#     - o pool VidProc escala pra cima e TAMBÉM pra baixo
#     - o workload completa as 5 fases sem ser cortado por tempo
#
# O cenário de 60 min (run_experiment.sh sem overrides) não é alterado por este
# script: tudo aqui é passado por variável de ambiente, nada é editado lá.
#
# Pico reduzido a 40 UEs de propósito: subir 100 UEs leva ~100s só nos sleeps de
# start, o que distorceria as fases curtas.
# ============================================================================

set -euo pipefail

SCENARIO="${1:-}"
case "$SCENARIO" in
    mab|rr|mab_lat|rr_lat) ;;
    *) echo "Uso: $0 {mab|rr|mab_lat|rr_lat}"; exit 1 ;;
esac

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"

# Fases: 60 + 180 + 90 + 300 + 120 = 750s (~12,5 min) + ~40s subindo UEs
#
# Os tempos de drain e settle são MAIORES que o resto de propósito — eles são o que
# este teste existe pra provar, e cada um tem um relógio do sistema que precisa caber
# dentro da fase:
#
#   drain 300s  → o mapeK tem COOLDOWN_SEC=30 e remove UMA instância por vez, então
#                 120s davam no máximo ~4 scale-downs. Com 300s cabem ~10, o
#                 suficiente pra ver o pool voltar ao baseline e não só esboçar a
#                 descida.
#   settle 120s → uma UE morta só some do ues_json depois do INACTIVITY_TIMEOUT=30s
#                 do mec_app_inteligence (reaper roda a cada 15s). Com settle de 30s o
#                 experimento acabava ANTES de as últimas UEs serem removidas e o CSV
#                 nunca mostrava a volta ao valor de warmup.
export WARMUP_UES=10
export PEAK_UES="${PEAK_UES:-40}"  # PEAK_UES=100 valida a carga do experimento completo
export PHASE_WARMUP_SEC=60
export PHASE_RAMP_SEC=180
export PHASE_PEAK_SEC=90
export PHASE_DRAIN_SEC=300
export PHASE_SETTLE_SEC=120

# Só define o timeout de segurança do script-pai (30 min), não corta o workload
export DURATION_MIN=15

# Separa os artefatos dos experimentos de verdade
export RUN_LABEL="short"

echo "============================================================"
echo "  CENÁRIO CURTO DE VALIDAÇÃO — $SCENARIO"
echo "  UEs:   $WARMUP_UES → $PEAK_UES → $WARMUP_UES"
echo "  Fases: warmup ${PHASE_WARMUP_SEC}s | ramp ${PHASE_RAMP_SEC}s | peak ${PHASE_PEAK_SEC}s |"
echo "         drain ${PHASE_DRAIN_SEC}s | settle ${PHASE_SETTLE_SEC}s  (~13 min no total)"
echo
echo "  O que conferir no resultado:"
echo "    1. num_services sobe E desce        (hoje: 8 subidas, 0 descidas)"
echo "    2. UEs voltam a $WARMUP_UES no settle      (hoje: ficam no pico pra sempre)"
echo "    3. 'workload concluiu as fases'     (hoje: cortado por timeout no drain)"
echo
echo "  Depois rode:  python3 analisa_execucao.py graficos/rl_input_state_${SCENARIO}_short.csv"
echo "============================================================"
echo

exec "$PROJECT_ROOT/run_experiment.sh" "$SCENARIO"
