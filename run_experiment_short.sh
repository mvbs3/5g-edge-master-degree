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
if [[ "$SCENARIO" != "mab" && "$SCENARIO" != "rr" ]]; then
    echo "Uso: $0 {mab|rr}"
    exit 1
fi

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"

# Fases: 60 + 120 + 60 + 120 + 30 = 390s (~6,5 min) + ~40s subindo UEs
export WARMUP_UES=10
export PEAK_UES=40
export PHASE_WARMUP_SEC=60
export PHASE_RAMP_SEC=120
export PHASE_PEAK_SEC=60
export PHASE_DRAIN_SEC=120
export PHASE_SETTLE_SEC=30

# Só define o timeout de segurança do script-pai (16 min), não corta o workload
export DURATION_MIN=8

# Separa os artefatos dos experimentos de verdade
export RUN_LABEL="short"

echo "============================================================"
echo "  CENÁRIO CURTO DE VALIDAÇÃO — $SCENARIO"
echo "  UEs:   $WARMUP_UES → $PEAK_UES → $WARMUP_UES"
echo "  Fases: warmup ${PHASE_WARMUP_SEC}s | ramp ${PHASE_RAMP_SEC}s | peak ${PHASE_PEAK_SEC}s |"
echo "         drain ${PHASE_DRAIN_SEC}s | settle ${PHASE_SETTLE_SEC}s"
echo
echo "  O que conferir no resultado:"
echo "    1. num_services sobe E desce (hoje só sobe)"
echo "    2. contagem de UEs volta a $WARMUP_UES no fim (hoje fica no pico)"
echo "    3. o script imprime 'workload concluiu as fases', sem aviso de timeout"
echo "============================================================"
echo

exec "$PROJECT_ROOT/run_experiment.sh" "$SCENARIO"
