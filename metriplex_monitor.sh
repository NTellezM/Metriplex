#!/bin/bash
source /opt/Metriplex/.secrets
# Metriplex Network Monitor — Telegram Alerts

BOT_TOKEN="${TELEGRAM_BOT_TOKEN}"
CHAT_ID="1165791849"
NODE_LOCAL="http://localhost:8000"
# MAX_BLOCK_AGE dinámico — función del número de validadores activos
# Con N validadores y block_time=10s, el líder mina ~1 de cada N slots
# threshold = 10s × N × 15  (buffer ×15 para tolerancia de red)
# Mínimo 120s, máximo 600s
_N_VALIDATORS=$(curl -sf --max-time 3 "$NODE_LOCAL/validators" 2>/dev/null | \
    python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('count',3))" 2>/dev/null)
_N_VALIDATORS=${_N_VALIDATORS:-3}
MAX_BLOCK_AGE=$(python3 -c "n=int('${_N_VALIDATORS}'); t=10*n*15; print(max(120,min(t,600)))")
STATE_FILE="/tmp/metriplex_monitor_state"

send_alert() {
    curl -s "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
        -d chat_id="${CHAT_ID}" \
        -d text="$1" \
        -d parse_mode="HTML" > /dev/null
}

# Cargar estado anterior
PREV_FORK_COUNT=0
PREV_ALERT=""
if [ -f "$STATE_FILE" ]; then
    source "$STATE_FILE"
fi

ALERTS=""
NOW=$(date '+%Y-%m-%d %H:%M:%S')

# ── 1. Relayer ────────────────────────────────────────────────
RELAYER=$(systemctl is-active metriplex-relayer.service 2>/dev/null)
if [ "$RELAYER" != "active" ]; then
    ALERTS="${ALERTS}🔴 <b>RELAYER CAÍDO</b>\n"
fi

# ── 2. Node-0 API ─────────────────────────────────────────────
INFO=$(curl -sf --max-time 5 "$NODE_LOCAL/info" 2>/dev/null)
if [ -z "$INFO" ]; then
    ALERTS="${ALERTS}🔴 <b>NODE-0 NO RESPONDE</b>\n"
else
    # ── 3. Chain liveness ─────────────────────────────────────
    H0=$(echo $INFO | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('chain_length',0))" 2>/dev/null)
    LAST_BLOCK=$(curl -sf --max-time 5 "$NODE_LOCAL/blocks?start=$((H0-1))&limit=1" 2>/dev/null)
    if [ -n "$LAST_BLOCK" ]; then
        TS=$(echo $LAST_BLOCK | python3 -c "import sys,json; b=json.load(sys.stdin); print(b[0]['timestamp'] if b else 0)" 2>/dev/null)
        NOW_TS=$(python3 -c "import time; print(int(time.time()))")
        AGE=$((NOW_TS - ${TS%.*}))
        if [ $AGE -gt $MAX_BLOCK_AGE ]; then
            ALERTS="${ALERTS}🔴 <b>CADENA DETENIDA</b> — último bloque hace ${AGE}s\n"
        fi
    fi

    # ── 4. Peers ──────────────────────────────────────────────
    # Contar peers activos via API
    NETWORK=$(curl -sf --max-time 5 "$NODE_LOCAL/network" 2>/dev/null)
    ACTIVE=0
    if [ -n "$NETWORK" ]; then
        ACTIVE=$(echo "$NETWORK" | python3 -c "
import sys,json
d=json.load(sys.stdin)
nodes = d.get('nodes',{})
print(sum(1 for k,v in nodes.items() if k != 'local' and v.get('online',False)))
" 2>/dev/null)
    fi
    ACTIVE=${ACTIVE:-0}
    if [ "$ACTIVE" -eq 0 ]; then
        ALERTS="${ALERTS}🔴 <b>NODO AISLADO</b> — 0 peers activos\n"
    fi

    # ── 5. Forks ──────────────────────────────────────────────
    FORK_COUNT=$(journalctl -u metriplex.service --since "5 minutes ago" --no-pager 2>/dev/null | \
        grep -c "bifurcación detectada" 2>/dev/null)
    FORK_COUNT=${FORK_COUNT:-0}
    if [ "$FORK_COUNT" -gt 3 ]; then
        ALERTS="${ALERTS}🟡 <b>FORKS FRECUENTES</b> — ${FORK_COUNT} en últimos 5min\n"
    fi

    # ── 6. Vault balance ──────────────────────────────────────
    VAULT=$(curl -sf --max-time 5 "$NODE_LOCAL/balance/f695d4a5" 2>/dev/null | \
        python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('balance_caf',0))" 2>/dev/null)
    VAULT=${VAULT:-0}
    if [ -n "$PREV_VAULT" ]; then
        DIFF=$(python3 -c "print(int($PREV_VAULT) - int($VAULT))" 2>/dev/null)
        if [ "${DIFF:-0}" -gt 10000 ]; then
            ALERTS="${ALERTS}🟡 <b>VAULT BAJÓ</b> — de ${PREV_VAULT} a ${VAULT} MPX\n"
        fi
    fi
fi

# ── Enviar alerta si hay problemas ────────────────────────────
if [ -n "$ALERTS" ]; then
    MSG="⚠️ <b>METRIPLEX ALERT</b> — ${NOW}\n\n${ALERTS}\n🔗 node-0: bloque ${H0:-?}"
    send_alert "$MSG"
fi

# Guardar estado
cat > "$STATE_FILE" << EOF
PREV_VAULT=${VAULT:-0}
PREV_FORK_COUNT=${FORK_COUNT:-0}
EOF

