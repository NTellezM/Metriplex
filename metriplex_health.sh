#!/bin/bash
# Metriplex Network Health Check
# Ejecutar desde el VPS: bash metriplex_health.sh

# ── Configuración ──────────────────────────────────────────────
NODE0="http://157.180.113.24:8000"
NODE2="http://190.82.149.108:8002"
NTLAP="http://190.82.149.108:8003"
VALIDATORS_URL="$NODE0/validators"
MAX_HEIGHT_DIFF=5
MAX_BLOCK_AGE=120  # segundos

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

# ── 1. API de cada nodo ────────────────────────────────────────
echo -e "\n${BOLD}  [1] API Status${RESET}"

get_info() {
  curl -sf --max-time 5 "$1/info" 2>/dev/null
}

INFO0=$(get_info $NODE0)
INFO2=$(get_info $NODE2)
INFOLAP=$(get_info $NTLAP)

[ -n "$INFO0" ]   && ok "node-0  ($NODE0) responde"   || fail "node-0  ($NODE0) no responde"
[ -n "$INFO2" ]   && ok "node-2  ($NODE2) responde"   || fail "node-2  ($NODE2) no responde"
[ -n "$INFOLAP" ] && ok "NT-lap  ($NTLAP) responde"   || fail "NT-lap  ($NTLAP) no responde"

# ── 2. Alturas ─────────────────────────────────────────────────
echo -e "\n${BOLD}  [2] Chain Heights${RESET}"

H0=$(echo $INFO0 | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('chain_length',0))" 2>/dev/null)
H2=$(echo $INFO2 | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('chain_length',0))" 2>/dev/null)
HLAP=$(echo $INFOLAP | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('chain_length',0))" 2>/dev/null)

H0=${H0:-0}; H2=${H2:-0}; HLAP=${HLAP:-0}

echo -e "    node-0 : ${BOLD}$H0${RESET}"
echo -e "    node-2 : ${BOLD}$H2${RESET}"
echo -e "    NT-lap : ${BOLD}$HLAP${RESET}"

HMAX=$(python3 -c "print(max($H0,$H2,$HLAP))")
HMIN=$(python3 -c "print(min(x for x in [$H0,$H2,$HLAP] if x > 0))")
DIFF=$((HMAX - HMIN))

[ $DIFF -le $MAX_HEIGHT_DIFF ] \
  && ok "Diferencia de altura: $DIFF bloques (≤ $MAX_HEIGHT_DIFF)" \
  || fail "Diferencia de altura: $DIFF bloques (> $MAX_HEIGHT_DIFF) — posible fork"

# ── 3. Hash común en bloque mínimo ────────────────────────────
echo -e "\n${BOLD}  [3] Hash Consensus${RESET}"

COMMON=$HMIN
if [ $COMMON -gt 1 ]; then
  COMMON=$((COMMON - 1))
  get_block_hash() {
    curl -sf --max-time 5 "$1/blocks?start=$COMMON&limit=1" 2>/dev/null | \
      python3 -c "import sys,json; b=json.load(sys.stdin); print(b[0]['hash'] if b else '')" 2>/dev/null
  }

  BH0=$(get_block_hash $NODE0)
  BH2=$(get_block_hash $NODE2)
  BHLAP=$(get_block_hash $NTLAP)

  if [ -n "$BH0" ] && [ "$BH0" = "$BH2" ] && [ "$BH0" = "$BHLAP" ]; then
    ok "Bloque $COMMON: hash idéntico en los 3 nodos"
    echo -e "    ${BH0:0:16}..."
  elif [ -z "$BH2" ] && [ -z "$BHLAP" ]; then
    warn "Solo node-0 respondió — no se puede comparar"
  else
    fail "Hash divergente en bloque $COMMON — FORK ACTIVO"
    [ -n "$BH0" ]   && echo -e "    node-0 : ${BH0:0:16}..."
    [ -n "$BH2" ]   && echo -e "    node-2 : ${BH2:0:16}..."
    [ -n "$BHLAP" ] && echo -e "    NT-lap : ${BHLAP:0:16}..."
  fi
else
  warn "Cadena muy corta para comparar hashes"
fi

# ── 4. Validadores FVR ────────────────────────────────────────
echo -e "\n${BOLD}  [4] FVR Validators${RESET}"

VALINFO=$(curl -sf --max-time 5 "$VALIDATORS_URL" 2>/dev/null)
if [ -n "$VALINFO" ]; then
  COUNT=$(echo $VALINFO | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('count',0))" 2>/dev/null)
  SLASHED=$(echo $VALINFO | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('slashed',[])))" 2>/dev/null)
  MODE=$(echo $VALINFO | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('mode','?'))" 2>/dev/null)

  ok "Modo: $MODE — $COUNT validadores activos"
  [ "$SLASHED" = "0" ] && ok "Sin validadores slashed" || fail "$SLASHED validador(es) slashed"

  echo $VALINFO | python3 -c "
import sys, json
d = json.load(sys.stdin)
for v in d.get('validators', []):
    print(f\"    {v['m3_hash'][:8]}  {v['endpoint']}  stake={v['stake_mpx']} MPX  reg=#{v['registered_at']}\")
" 2>/dev/null
else
  fail "No se pudo obtener info de validadores"
fi

# ── 5. Bloque reciente (cadena viva) ──────────────────────────
echo -e "\n${BOLD}  [5] Chain Liveness${RESET}"

LAST_HASH=$(echo $INFO0 | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('latest_block_hash',''))" 2>/dev/null)
LAST_BLOCK=$(curl -sf --max-time 5 "$NODE0/blocks?start=$((H0-1))&limit=1" 2>/dev/null)
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

# ── 6. Peers por nodo ─────────────────────────────────────────
echo -e "\n${BOLD}  [6] Peer Connections${RESET}"

get_peers() {
  curl -sf --max-time 5 "$1/peers" 2>/dev/null | \
    python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d) if isinstance(d,list) else d.get('count',0))" 2>/dev/null
}

P0=$(get_peers $NODE0)
P2=$(get_peers $NODE2)
PLAP=$(get_peers $NTLAP)

P0=${P0:-"?"}; P2=${P2:-"?"}; PLAP=${PLAP:-"?"}

echo -e "    node-0 : $P0 peers"
echo -e "    node-2 : $P2 peers"
echo -e "    NT-lap : $PLAP peers"

# ── Resumen ───────────────────────────────────────────────────
sep
if [ $FAILURES -eq 0 ]; then
  echo -e "\n  ${GREEN}${BOLD}✓ RED SALUDABLE — 0 fallas${RESET}\n"
else
  echo -e "\n  ${RED}${BOLD}✗ $FAILURES FALLA(S) DETECTADA(S)${RESET}\n"
fi
