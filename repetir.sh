#!/usr/bin/env bash
# ============================================================================
# Repetições do experimento completo, para média e IC 95% por cenário.
#
#   ./repetir.sh                          → 3 repetições dos 12 cenários (mab, rr, mabsem × 4)
#   REPETICOES=5 ./repetir.sh             → 5 repetições
#   REPETICOES=3 ./repetir.sh mab_lat rr_lat   → só o cenário 2
#
# Cada execução chama ./testar_agora.sh <cenario> completo (~60 min), que já zera o
# pool, reinicia catcher/inteligência/MAPE-K e arquiva a run em runs/. Os cenários são
# intercalados dentro de cada repetição (mab, rr, mab_lat, rr_lat, mab, rr, ...) para
# que uma deriva do servidor ao longo da noite não caia toda num cenário só.
#
# Um cenário que falha não interrompe os outros: o resumo no fim lista as falhas.
# Depois:  cd graficos && python3 agregar_repeticoes.py --desde AAAAMMDD
# ============================================================================

set -uo pipefail

REPETICOES="${REPETICOES:-3}"
if [[ $# -gt 0 ]]; then
    CENARIOS=("$@")
else
    CENARIOS=(mab rr mabsem mab_lat rr_lat mabsem_lat mab_het rr_het mabsem_het mab_var rr_var mabsem_var)
fi
for c in "${CENARIOS[@]}"; do
    case "$c" in mab|rr|mabsem|mab_lat|rr_lat|mabsem_lat|mab_het|rr_het|mabsem_het|mab_var|rr_var|mabsem_var) ;; *) echo "Cenário inválido: $c (use mab, rr ou mabsem, com ou sem _lat/_het/_var)"; exit 1 ;; esac
done

RAIZ="$(cd "$(dirname "$0")" && pwd)"
cd "$RAIZ"
mkdir -p logs

INICIO="$(date +%Y%m%d)"
TOTAL=$((REPETICOES * ${#CENARIOS[@]}))
echo "============================================================"
echo "  $REPETICOES repetição(ões) de: ${CENARIOS[*]}"
echo "  $TOTAL execuções, ~$((TOTAL * 65 / 60)) h no total"
echo "============================================================"

falhas=()
n=0
for rep in $(seq 1 "$REPETICOES"); do
    for c in "${CENARIOS[@]}"; do
        n=$((n + 1))
        echo
        echo "################ [$n/$TOTAL] repetição $rep — $c — $(date +%H:%M:%S) ################"
        ./testar_agora.sh "$c" completo 2>&1 | tee "logs/repeticao${rep}_${c}_$(date +%Y%m%d_%H%M%S).log"
        status=${PIPESTATUS[0]}
        if [[ "$status" != "0" ]]; then
            falhas+=("repetição $rep / $c (código $status)")
        fi
    done
done

echo
echo "============================================================"
echo "  Repetições concluídas às $(date +%H:%M:%S)"
if [[ ${#falhas[@]} -eq 0 ]]; then
    echo "  Todas as $TOTAL execuções terminaram sem erro."
else
    echo "  ${#falhas[@]} execução(ões) com erro — confira os logs/repeticao*.log:"
    printf '    - %s\n' "${falhas[@]}"
fi
echo
echo "  Para agregar (média, desvio e IC 95%):"
echo "    cd graficos && python3 agregar_repeticoes.py --desde $INICIO"
echo "============================================================"
