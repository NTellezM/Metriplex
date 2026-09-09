#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Metriplex — register-validator.sh
#  Registra este nodo como validador en el FVR una vez que su identidad tiene
#  el stake de 100 MPX. Firma con la clave del keystore (password desde .env),
#  y al registrarse cambia el servicio de observador a minero.
#
#    bash scripts/register-validator.sh --api-port 8003 --public-ip 5.78.209.5
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

API_PORT=8000
PUBLIC_IP=""
NODE_DIR="/opt/Metriplex"

while [ $# -gt 0 ]; do
  case "$1" in
    --api-port)  API_PORT="$2"; shift ;;
    --public-ip) PUBLIC_IP="$2"; shift ;;
    --dir)       NODE_DIR="$2"; shift ;;
    *) echo "Flag desconocido: $1" >&2; exit 2 ;;
  esac
  shift
done

ok()   { printf "\033[1;32m  ✓ %s\033[0m\n" "$*"; }
die()  { printf "\033[1;31m  ✗ %s\033[0m\n" "$*" >&2; exit 1; }

cd "$NODE_DIR"
KS="keystore_${API_PORT}.json"
API="http://localhost:${API_PORT}"

[ -f "$KS" ] || die "No existe $KS. ¿Corriste join.sh --validator en este nodo?"
[ -f ".env.${API_PORT}" ] || die "No existe .env.${API_PORT} con la contraseña del keystore."

PW="$(sed -n 's/^MINER_PASSWORD=//p' ".env.${API_PORT}" | head -1)"
[ -n "$PW" ] || die "MINER_PASSWORD no está en .env."

# Endpoint público:p2p — deducir p2p-port del servicio en ejecución
P2P_PORT="$(sed -n "s/.*--p2p-port \([0-9]*\).*/\1/p" "/etc/systemd/system/metriplex-${API_PORT}.service" 2>/dev/null | head -1)"
[ -n "$P2P_PORT" ] || P2P_PORT=$((API_PORT - 8000 + 65432))
if [ -z "$PUBLIC_IP" ]; then
  PUBLIC_IP="$(curl -sf --max-time 8 https://api.ipify.org 2>/dev/null || true)"
  [ -n "$PUBLIC_IP" ] || die "No pude detectar la IP pública; pásala con --public-ip."
fi
ENDPOINT="${PUBLIC_IP}:${P2P_PORT}"

echo "▸ Registrando validador  endpoint=${ENDPOINT}  api=${API}"
# El tool ya verifica stake>=100, calcula λ, chequea diversidad, firma y envía.
./venv/bin/python3 tools/register_validator.py \
  --keystore "$KS" --password "$PW" --endpoint "$ENDPOINT" --api "$API" \
  || die "El registro falló (ver mensaje arriba: stake insuficiente o diversidad geométrica)."

# Esperar a que el registro se mine y confirmar en el FVR
IDENT="$(./venv/bin/python3 -c "import json,hashlib; d=json.load(open('$KS')); m3=d.get('public_m3') or d['keystore']['public_m3']; print(hashlib.sha256(json.dumps(m3,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:8])")"
for i in $(seq 1 20); do
  if curl -fsS --max-time 5 "${API}/validators" 2>/dev/null | grep -q "$IDENT"; then
    ok "validador ${IDENT} activo en el FVR"
    REGISTRADO=1; break
  fi
  sleep 4
done
[ "${REGISTRADO:-0}" = 1 ] || die "el registro no apareció en el FVR tras esperar; revisa el balance/stake."

# Cambiar el servicio de observador a minero
SVC="metriplex-${API_PORT}"
UNIT="/etc/systemd/system/${SVC}.service"
if grep -q -- "--no-miner" "$UNIT"; then
  echo "▸ Cambiando el servicio a modo minero"
  sed -i "s#--no-miner#--miner-wallet ${NODE_DIR}/${KS}#" "$UNIT"
  systemctl daemon-reload
  systemctl restart "$SVC"
  sleep 6
  systemctl is-active --quiet "$SVC" && ok "servicio ${SVC} reiniciado como minero" || die "el servicio no reinició"
fi

echo
printf "\033[1;32m═══ Validador activo ═══\033[0m\n"
echo "  identidad: ${IDENT}   endpoint: ${ENDPOINT}"
echo "  verifica:  curl -s ${API}/validators | grep ${IDENT}"
