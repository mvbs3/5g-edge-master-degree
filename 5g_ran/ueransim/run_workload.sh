#!/usr/bin/env bash
# ============================================================================
# Workload phased UE generator — roda DENTRO do container nr_ue.
# Mountado em /mnt/ueransim/run_workload.sh.
#
# Fases (60 min total):
#   1. Warmup       0–10 min     →  10 UEs (estabiliza com MIN_INSTANCES)
#   2. Ramp up      10–25 min    →  +90 UEs em 15 min (1 a cada 10s)
#   3. Peak         25–40 min    →  100 UEs sustentados
#   4. Drain        40–55 min    →  mata 90 UEs em 15 min (1 a cada 10s)
#   5. Settle       55–60 min    →  10 UEs até o fim
#
# As variáveis WARMUP_UES / PEAK_UES / PHASE_*_SEC permitem override.
# Cada UE roda ue_client.py em background; o PID fica em /tmp/ue_pids/ue_<i>.pid
# pra que o drain mate UEs específicos.
# ============================================================================
set -u

WARMUP_UES=${WARMUP_UES:-10}
PEAK_UES=${PEAK_UES:-100}
PHASE_WARMUP_SEC=${PHASE_WARMUP_SEC:-600}
PHASE_RAMP_SEC=${PHASE_RAMP_SEC:-900}
PHASE_PEAK_SEC=${PHASE_PEAK_SEC:-900}
PHASE_DRAIN_SEC=${PHASE_DRAIN_SEC:-900}
PHASE_SETTLE_SEC=${PHASE_SETTLE_SEC:-300}

PID_DIR="/tmp/ue_pids"
LOG_DIR="/mnt/ueransim/logs_workload"
mkdir -p "$PID_DIR" "$LOG_DIR"

log() { echo "[$(date +%H:%M:%S)] $*"; }

start_ue() {
    local i=$1
    python3 /mnt/ueransim/ue_client.py "$i" > "$LOG_DIR/ue_$i.log" 2>&1 &
    echo $! > "$PID_DIR/ue_$i.pid"
}

stop_ue() {
    local i=$1
    if [[ -f "$PID_DIR/ue_$i.pid" ]]; then
        kill "$(cat "$PID_DIR/ue_$i.pid")" 2>/dev/null || true
        rm -f "$PID_DIR/ue_$i.pid"
    fi
}

cleanup() {
    log "Cleanup: matando todos os UEs"
    for f in "$PID_DIR"/ue_*.pid; do
        [[ -f "$f" ]] || continue
        kill "$(cat "$f")" 2>/dev/null || true
        rm -f "$f"
    done
}
trap cleanup EXIT INT TERM

ramp_count=$((PEAK_UES - WARMUP_UES))
ramp_step=$((PHASE_RAMP_SEC / ramp_count))
[[ "$ramp_step" -lt 1 ]] && ramp_step=1

log "=== INÍCIO ==="
log "WARMUP_UES=$WARMUP_UES PEAK_UES=$PEAK_UES ramp_step=${ramp_step}s"

# Fase 1 — Warmup
log "Fase 1/5 WARMUP — subindo $WARMUP_UES UEs"
for i in $(seq 1 "$WARMUP_UES"); do
    start_ue "$i"
    sleep 1
done
log "Mantendo warmup por ${PHASE_WARMUP_SEC}s"
sleep "$PHASE_WARMUP_SEC"

# Fase 2 — Ramp up
log "Fase 2/5 RAMP UP de $WARMUP_UES → $PEAK_UES UEs em ${PHASE_RAMP_SEC}s"
for i in $(seq $((WARMUP_UES + 1)) "$PEAK_UES"); do
    start_ue "$i"
    sleep "$ramp_step"
done

# Fase 3 — Peak
log "Fase 3/5 PEAK — $PEAK_UES UEs por ${PHASE_PEAK_SEC}s"
sleep "$PHASE_PEAK_SEC"

# Fase 4 — Drain
log "Fase 4/5 DRAIN — matando $ramp_count UEs em ${PHASE_DRAIN_SEC}s"
drain_step=$((PHASE_DRAIN_SEC / ramp_count))
[[ "$drain_step" -lt 1 ]] && drain_step=1
for i in $(seq "$PEAK_UES" -1 $((WARMUP_UES + 1))); do
    stop_ue "$i"
    sleep "$drain_step"
done

# Fase 5 — Settle
log "Fase 5/5 SETTLE — mantendo $WARMUP_UES UEs por ${PHASE_SETTLE_SEC}s"
sleep "$PHASE_SETTLE_SEC"

log "=== FIM ==="
