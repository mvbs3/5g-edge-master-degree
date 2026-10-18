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
#   - devolve o pool VidProc ao baseline (mantém KEEP_MIN instâncias) pra que os
#     dois cenários partam do mesmo ponto
#   - copia run_workload.sh pra dentro do container nr_ue
#   - dispara o workload em background no container
#   - AGUARDA o workload concluir as 5 fases (warmup/ramp/peak/drain/settle)
#   - mata UEs remanescentes
#   - arquiva os CSVs em runs/<scenario>_<timestamp>/
#   - copia o rl_input_state.csv pra graficos/ com nome do cenário
#   - devolve o pool ao baseline no fim, pra não deixar instâncias órfãs
# ============================================================================

set -euo pipefail

SCENARIO="${1:-}"
if [[ "$SCENARIO" != "mab" && "$SCENARIO" != "rr" ]]; then
    echo "Uso: $0 {mab|rr}"
    exit 1
fi

# DURATION_MIN é a duração ESPERADA do workload (as 5 fases do run_workload.sh somam
# 60 min). Ela não corta mais o experimento: serve de referência e de base para o
# timeout de segurança. Para mudar a duração real, ajuste as PHASE_*_SEC do workload.
DURATION_MIN="${DURATION_MIN:-60}"

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
# RUN_LABEL marca execuções que não são experimento (ex: o cenário curto de
# validação), pra que elas não sobrescrevam os CSVs usados nos gráficos finais.
# Vazio = comportamento original, intocado.
RUN_LABEL="${RUN_LABEL:-}"
RUN_SUFFIX=""
[[ -n "$RUN_LABEL" ]] && RUN_SUFFIX="_${RUN_LABEL}"
RUN_DIR="$PROJECT_ROOT/runs/${SCENARIO}${RUN_SUFFIX}_${RUN_TS}"
GRAFICOS_DIR="$PROJECT_ROOT/graficos"
mkdir -p "$RUN_DIR"

# Devolve o pool VidProc ao baseline, matando as instâncias de índice >= KEEP_MIN e
# desregistrando-as do service_registry. Mantém 0..KEEP_MIN-1 vivas: zerar o pool
# deixaria as UEs sem nenhuma instância pra atender ("Nenhum app disponível para
# app_type") e o MAPE-K não recria instâncias por conta própria — ele só escala a
# partir do que existe. Mesma semântica de cleanup_extra_mec_instances() no
# automacao_script.py, repetida aqui pra que o experimento não dependa dele.
# Sem este reset, o pool sobrevive de um cenário pro outro: se o MAB termina em 10
# instâncias, o RR COMEÇA em 10 e a comparação deixa de ser válida.
KEEP_MIN="${KEEP_MIN:-2}"

reset_vidproc_pool() {
    local phase="$1"
    echo "  Devolvendo o pool VidProc ao baseline de $KEEP_MIN instância(s) ($phase)..."

    local containers
    containers=$(docker ps -a --format '{{.Names}}' | grep -E '^mec_app1_instance[0-9]+$' || true)

    if [[ -z "$containers" ]]; then
        echo "    AVISO: nenhuma instância VidProc encontrada — o stack está de pé?"
        return 0
    fi

    local removed=0
    for container in $containers; do
        local index="${container#mec_app1_instance}"
        if (( index < KEEP_MIN )); then
            continue
        fi
        echo "    parando $container (VideoStreamingService${index})"
        python3 "$PROJECT_ROOT/mec_instance_manager.py" stop "$container" \
            --mec_name "VideoStreamingService${index}" >/dev/null 2>&1 || \
            echo "    AVISO: falha ao parar $container"
        docker rm -f "$container" >/dev/null 2>&1 || true
        removed=$((removed + 1))
    done

    if (( removed == 0 )); then
        echo "    pool já estava no baseline"
    else
        echo "    $removed instância(s) removida(s)"
    fi
}

echo "============================================================"
echo "  EXPERIMENTO: $SCENARIO (~$DURATION_MIN min, definido pelas fases do workload)"
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
echo "[1/6] Limpando CSVs anteriores..."
rm -f "$PROJECT_ROOT/mec_apps/Results/rewards.csv"
rm -f "$PROJECT_ROOT/mec_apps/Results/arm_probabilities.csv"
rm -f "$PROJECT_ROOT/mec_apps/rl_input_state.csv"

# 1b. Zera o pool: os dois cenários precisam partir do mesmo número de instâncias
reset_vidproc_pool "antes do cenário"
sleep 5

# 2. Copia workload e dispara
echo "[2/6] Disparando workload no nr_ue..."
docker cp "$PROJECT_ROOT/5g_ran/ueransim/run_workload.sh" nr_ue:/mnt/ueransim/run_workload.sh
docker exec nr_ue chmod +x /mnt/ueransim/run_workload.sh

# O ambiente do host NÃO atravessa o docker exec, então cada variável de fase precisa
# ser repassada explicitamente com -e. Sem isso o workload sempre usava os defaults
# (60 min no total) e não havia como rodar um cenário curto de validação.
WORKLOAD_ENV=()
for var in WARMUP_UES PEAK_UES PHASE_WARMUP_SEC PHASE_RAMP_SEC PHASE_PEAK_SEC \
           PHASE_DRAIN_SEC PHASE_SETTLE_SEC; do
    if [[ -n "${!var:-}" ]]; then
        WORKLOAD_ENV+=(-e "$var=${!var}")
        echo "  override: $var=${!var}"
    fi
done

# A expansão usa a forma ${A[@]+...} porque com `set -u` um array vazio quebra em
# bash 3.2 (o do macOS): sem override nenhum, "${WORKLOAD_ENV[@]}" seria unbound.
docker exec -d ${WORKLOAD_ENV[@]+"${WORKLOAD_ENV[@]}"} nr_ue bash -c \
    "/mnt/ueransim/run_workload.sh > /mnt/ueransim/workload_${SCENARIO}_${RUN_TS}.log 2>&1"
START_TS=$(date +%s)

# 3. Espera o workload terminar as 5 fases por conta própria
# Antes esperávamos DURATION_MIN fixo e matávamos o workload no fim. As fases do
# run_workload.sh somam exatamente 3600s, e os ~100s gastos subindo as UEs no warmup
# já empurram o fim para além dos 60 min — então o pkill caía DENTRO do peak ou do
# drain e as fases 4 e 5 nunca aconteciam. Era por isso que as UEs subiam para 100 e
# nunca voltavam para 10: o experimento era cortado antes do drain.
# Agora quem define o fim é o próprio workload; TIMEOUT_MIN é só rede de segurança.
TIMEOUT_MIN="${TIMEOUT_MIN:-$((DURATION_MIN * 2))}"
TIMEOUT_SEC=$((TIMEOUT_MIN * 60))
echo "[3/6] Aguardando o workload concluir as 5 fases (timeout de segurança: $TIMEOUT_MIN min)..."
workload_finished=false
while :; do
    elapsed=$(( $(date +%s) - START_TS ))

    if ! docker exec nr_ue pgrep -f "run_workload.sh" >/dev/null 2>&1; then
        workload_finished=true
        printf "\r  workload concluiu as fases em %d s (%d min)\n" "$elapsed" "$((elapsed / 60))"
        break
    fi

    if (( elapsed >= TIMEOUT_SEC )); then
        printf "\r  AVISO: timeout de %d min atingido com o workload ainda rodando\n" "$TIMEOUT_MIN"
        echo "         As fases de drain/settle podem não ter completado — confira o log do workload."
        break
    fi

    printf "\r  [%d s decorridos] aguardando fim do workload..." "$elapsed"
    sleep 30
done

# 4. Mata UEs e o workload script
echo "[4/6] Garantindo que nenhuma UE ficou viva..."
if [[ "$workload_finished" == false ]]; then
    docker exec nr_ue pkill -f "run_workload.sh" || true
fi
docker exec nr_ue pkill -f "ue_client.py" || true
sleep 5

# 5. Arquiva resultados
echo "[5/6] Arquivando resultados..."
if [[ -f "$PROJECT_ROOT/mec_apps/rl_input_state.csv" ]]; then
    cp "$PROJECT_ROOT/mec_apps/rl_input_state.csv" "$RUN_DIR/rl_input_state.csv"
    cp "$PROJECT_ROOT/mec_apps/rl_input_state.csv" "$GRAFICOS_DIR/rl_input_state_${SCENARIO}${RUN_SUFFIX}.csv"
else
    echo "  AVISO: rl_input_state.csv não foi gerado — verifique mec_app_inteligence."
fi
cp -r "$PROJECT_ROOT/mec_apps/Results" "$RUN_DIR/Results" 2>/dev/null || true
docker cp "nr_ue:/mnt/ueransim/workload_${SCENARIO}_${RUN_TS}.log" "$RUN_DIR/" 2>/dev/null || true

# 6. Volta o pool ao baseline depois de arquivar, pra não deixar instâncias órfãs
echo "[6/6] Devolvendo o pool VidProc ao baseline..."
reset_vidproc_pool "depois do cenário"

echo "============================================================"
echo "  Experimento $SCENARIO finalizado."
echo "  Resultado:        $RUN_DIR"
echo "  CSV pra gráficos: $GRAFICOS_DIR/rl_input_state_${SCENARIO}${RUN_SUFFIX}.csv"
echo
echo "  Próximos passos:"
echo "    - Rode o outro cenário (mab ou rr)"
echo "    - Quando tiver os 2 CSVs, gere os gráficos:"
echo "        cd $GRAFICOS_DIR && python3 graficos_compare.py"
echo "============================================================"
