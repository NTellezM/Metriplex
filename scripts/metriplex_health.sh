#!/bin/bash
# Metriplex Network Health Check
# Ejecutar desde el VPS: bash metriplex_health.sh

# ── Configuración ──────────────────────────────────────────────
NODE0="http://157.180.113.24:8000"
NODE0_LOCAL="http://localhost:8000"
MAX_HEIGHT_DIFF=5
MAX_BLOCK_AGE=120

# ── Colores ────────────────────────────────────────────────────
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

ok()   { echo -e "  ${GREEN}✓${RESET} $1"; }
fail() { echo -e "  ${RED}✗${RESET} $1"; FAILURES=$((FAILURES+1)); }
warn() { echo -e "  ${YELLOW}⚠${RESET} $1"; }
sep()  { echo -e "${CYAN}──────────────────────────────────────────${RESET}"; }

FAILURES=0

echo ""
echo -e "${BOLD}  METRIPLEX NETWORK HEALTH CHECK${RESET}"
echo -e "  $(date '+%Y-%m-%d %H:%M:%S')"
sep

# ── 1. API node-0 ─────────────────────────────────────────────
echo -e "\n${BOLD}  [1] API Status${RESET}"

INFO0=$(curl -sf --max-time 5 "$NODE0_LOCAL/info" 2>/dev/null)
[ -n "$INFO0" ] && ok "node-0  ($NODE0) responde" || fail "node-0  ($NODE0) no responde"

# ── 2. Peers conectados (desde node-0) ────────────────────────
echo -e "\n${BOLD}  [2] Peers conectados a node-0${RESET}"

PEER_INFO=$(journalctl -u metriplex.service -n 50 --no-pager 2>/dev/null | grep "Mantenimiento" | tail -1)
ACTIVE_PEERS=$(echo "$PEER_INFO" | grep -oP '\d+ peers activos' | grep -oP '\d+')
WAITING_PEERS=$(echo "$PEER_INFO" | grep -oP '\d+ en espera' | grep -oP '\d+')
ACTIVE_PEERS=${ACTIVE_PEERS:-0}

if [ "$ACTIVE_PEERS" -ge 2 ]; then
    ok "$ACTIVE_PEERS peers activos, $WAITING_PEERS en espera"
elif [ "$ACTIVE_PEERS" -eq 1 ]; then
    warn "$ACTIVE_PEERS peer activo — red parcialmente conectada"
else
    fail "0 peers activos — nodo aislado"
fi

# Peers conocidos desde FVR
VALIDATORS=$(curl -sf --max-time 5 "$NODE0_LOCAL/validators" 2>/dev/null)
if [ -n "$VALIDATORS" ]; then
    echo "$VALIDATORS" | python3 -c "
import sys, json, subprocess, requests
d = json.load(sys.stdin)
for v in d.get('validators', []):
    ep = v['endpoint']
    host, port = ep.rsplit(':', 1)
    api_port = int(port) - 57432
    try:
        r = requests.get(f'http://{host}:{api_port}/info', timeout=3)
        info = r.json()
        h = info.get('chain_length', '?')
        print(f'    {v[\"m3_hash\"][:8]}  {ep}  altura={h}  ✓')
    except:
        print(f'    {v[\"m3_hash\"][:8]}  {ep}  altura=NAT/offline')
" 2>/dev/null
fi

# ── 3. Chain Heights ───────────────────────────────────────────
echo -e "\n${BOLD}  [3] Chain Heights${RESET}"

H0=$(echo $INFO0 | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('chain_length',0))" 2>/dev/null)
H0=${H0:-0}
echo -e "    node-0 : ${BOLD}$H0${RESET} bloques"

# Alturas de Chile desde logs de node-0
CHILE_HEIGHTS=$(journalctl -u metriplex.service -n 100 --no-pager 2>/dev/null | \
    grep "Nodo 190\." | grep -oP 'Desde \d+ a \d+' | tail -3)
if [ -n "$CHILE_HEIGHTS" ]; then
    echo -e "    Chile  : última actividad detectada"
    echo "$CHILE_HEIGHTS" | while read line; do echo -e "             $line"; done
fi

# ── 4. Validadores FVR ────────────────────────────────────────
echo -e "\n${BOLD}  [4] FVR Validators${RESET}"

if [ -n "$VALIDATORS" ]; then
    COUNT=$(echo $VALIDATORS | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('count',0))" 2>/dev/null)
    SLASHED=$(echo $VALIDATORS | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('slashed',[])))" 2>/dev/null)
    MODE=$(echo $VALIDATORS | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('mode','?'))" 2>/dev/null)
    ok "Modo: $MODE — $COUNT validadores activos"
    [ "$SLASHED" = "0" ] && ok "Sin validadores slashed" || fail "$SLASHED validador(es) slashed"
    echo $VALIDATORS | python3 -c "
import sys, json
d = json.load(sys.stdin)
for v in d.get('validators', []):
    print(f\"    {v['m3_hash'][:8]}  {v['endpoint']}  stake={v['stake_mpx']} MPX  reg=#{v['registered_at']}\")
" 2>/dev/null
else
    fail "No se pudo obtener info de validadores"
fi

# ── 5. Chain Liveness ─────────────────────────────────────────
echo -e "\n${BOLD}  [5] Chain Liveness${RESET}"

LAST_BLOCK=$(curl -sf --max-time 5 "$NODE0_LOCAL/blocks?start=$((H0-1))&limit=1" 2>/dev/null)
if [ -n "$LAST_BLOCK" ]; then
    TS=$(echo $LAST_BLOCK | python3 -c "import sys,json; b=json.load(sys.stdin); print(b[0]['timestamp'] if b else 0)" 2>/dev/null)
    NOW=$(python3 -c "import time; print(time.time())")
    AGE=$(python3 -c "print(int($NOW - $TS))")
    [ $AGE -le $MAX_BLOCK_AGE ] \
        && ok "Último bloque hace ${AGE}s (≤ ${MAX_BLOCK_AGE}s)" \
        || fail "Último bloque hace ${AGE}s (> ${MAX_BLOCK_AGE}s) — cadena detenida"
else
    warn "No se pudo obtener timestamp del último bloque"
fi

# ── 6. Relayer ────────────────────────────────────────────────
echo -e "\n${BOLD}  [6] Relayer${RESET}"

RELAYER_STATUS=$(systemctl is-active metriplex-relayer.service 2>/dev/null)
[ "$RELAYER_STATUS" = "active" ] && ok "Relayer activo" || fail "Relayer caído"

VAULT_BAL=$(curl -sf --max-time 5 "$NODE0_LOCAL/balance/f695d4a5" 2>/dev/null | \
    python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('balance_caf','?'))" 2>/dev/null)
[ -n "$VAULT_BAL" ] && echo -e "    Vault: ${BOLD}$VAULT_BAL MPX${RESET}"

# ── 7. Forks recientes ────────────────────────────────────────
echo -e "\n${BOLD}  [7] Forks recientes (última hora)${RESET}"

FORK_COUNT=$(journalctl -u metriplex.service --since "1 hour ago" --no-pager 2>/dev/null | \
    grep -c "bifurcación detectada" 2>/dev/null)
FORK_COUNT=${FORK_COUNT:-0}

if [ "$FORK_COUNT" -eq 0 ]; then
    ok "Sin forks en la última hora"
elif [ "$FORK_COUNT" -le 5 ]; then
    warn "$FORK_COUNT eventos de fork en la última hora"
else
    fail "$FORK_COUNT eventos de fork en la última hora — red inestable"
fi

# ── Resumen ───────────────────────────────────────────────────
sep
if [ $FAILURES -eq 0 ]; then
    echo -e "\n  ${GREEN}${BOLD}✓ RED SALUDABLE — 0 fallas${RESET}\n"
else
    echo -e "\n  ${RED}${BOLD}✗ $FAILURES FALLA(S) DETECTADA(S)${RESET}\n"
fi
