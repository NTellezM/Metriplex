#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Metriplex — join.sh
#  De cero a nodo corriendo (con systemd) en un solo comando.
#
#    curl -sSL https://metriplexmpx.xyz/join.sh | bash                # observador
#    curl -sSL https://metriplexmpx.xyz/join.sh | bash -s -- --validator
#
#  Flags: --validator | --observer (def) | --api-port N | --p2p-port N
#         --peer IP:PUERTO | --public-ip IP | --dir RUTA
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

ROLE=observer
API_PORT=8000
P2P_PORT=65432
PEER="157.180.113.24:65432"
PUBLIC_IP=""
NODE_DIR="/opt/Metriplex"
REPO="https://github.com/NTellezM/Metriplex"

while [ $# -gt 0 ]; do
  case "$1" in
    --validator) ROLE=validator ;;
    --observer)  ROLE=observer ;;
    --api-port)  API_PORT="$2"; shift ;;
    --p2p-port)  P2P_PORT="$2"; shift ;;
    --peer)      PEER="$2"; shift ;;
    --public-ip) PUBLIC_IP="$2"; shift ;;
    --dir)       NODE_DIR="$2"; shift ;;
    *) echo "Flag desconocido: $1" >&2; exit 2 ;;
  esac
  shift
done

say()  { printf "\033[1;36m▸ %s\033[0m\n" "$*"; }
ok()   { printf "\033[1;32m  ✓ %s\033[0m\n" "$*"; }
warn() { printf "\033[1;33m  ! %s\033[0m\n" "$*"; }
die()  { printf "\033[1;31m  ✗ %s\033[0m\n" "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Ejecuta como root (systemd requiere privilegios)."

# 1. Dependencias del sistema
say "Verificando dependencias"
command -v git >/dev/null || die "Falta git: sudo apt install git"
command -v python3 >/dev/null || die "Falta python3: sudo apt install python3 python3-venv"
command -v sqlite3 >/dev/null || { warn "instalando sqlite3"; apt-get install -y -qq sqlite3 >/dev/null 2>&1 || true; }
ok "git, python3 presentes"

# 2. Repositorio
if [ ! -d "$NODE_DIR/.git" ]; then
  say "Clonando repositorio en $NODE_DIR"
  git clone --quiet "$REPO" "$NODE_DIR"
else
  say "Repositorio ya presente en $NODE_DIR"
fi
cd "$NODE_DIR"

# 3. Entorno virtual + dependencias
say "Instalando entorno Python"
[ -d venv ] || python3 -m venv venv
./venv/bin/pip install --quiet --upgrade pip
./venv/bin/pip install --quiet -r requirements.txt
ok "dependencias instaladas"

# 4. Puertos libres (permite varios nodos en la misma máquina)
libre() { ! ss -tuln 2>/dev/null | grep -q ":$1 "; }
while ! libre "$API_PORT"; do API_PORT=$((API_PORT+1)); done
while ! libre "$P2P_PORT"; do P2P_PORT=$((P2P_PORT+1)); done
ok "puertos: API=$API_PORT  P2P=$P2P_PORT"

DB_FILE="node_data_${API_PORT}.db"

# 5. Bootstrap por snapshot (rápido)
if [ ! -f "$DB_FILE" ]; then
  say "Descargando snapshot (bootstrap rápido)"
  bash scripts/bootstrap.sh "$DB_FILE" || warn "bootstrap falló; el nodo sincronizará desde P2P (más lento)"
else
  ok "DB local ya existe: $DB_FILE"
fi

# 6. Keystore + password (solo validador)
# Cada nodo usa su propio archivo de entorno (.env.<puerto>) para no pisar
# la contraseña de otros nodos en la misma máquina.
ENVFILE="$NODE_DIR/.env.${API_PORT}"
touch "$ENVFILE"; chmod 600 "$ENVFILE"
MINER_ARG="--no-miner"
IDENTITY=""
if [ "$ROLE" = validator ]; then
  KS="keystore_${API_PORT}.json"
  if [ ! -f "$KS" ]; then
    say "Generando identidad fractal (keystore) — puede tardar ~30s"
    PW="$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')"
    IDENTITY="$(./venv/bin/python3 scripts/gen_node_keystore.py "$KS" "$PW" | sed -n 's/^IDENTITY=//p')"
    grep -q "^MINER_PASSWORD=" "$ENVFILE" && sed -i '/^MINER_PASSWORD=/d' "$ENVFILE"
    echo "MINER_PASSWORD=$PW" >> "$ENVFILE"
    ok "keystore: $KS  ·  identidad ${IDENTITY:0:16}…  ·  password en $(basename "$ENVFILE") (600)"
  else
    ok "keystore ya existe: $KS"
  fi
  MINER_ARG="--miner-wallet $NODE_DIR/$KS"
fi

# 7. Servicio systemd (con endurecimiento de apagado)
SVC="metriplex-${API_PORT}"
say "Creando servicio systemd: $SVC"
PUBIP_ARG=""; [ -n "$PUBLIC_IP" ] && PUBIP_ARG="--public-ip $PUBLIC_IP"
cat > "/etc/systemd/system/${SVC}.service" <<UNIT
[Unit]
Description=Metriplex Node (${ROLE}, api ${API_PORT})
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$NODE_DIR
EnvironmentFile=$NODE_DIR/.env.${API_PORT}
ExecStart=$NODE_DIR/venv/bin/python3 -u main.py --api-port ${API_PORT} --p2p-port ${P2P_PORT} --peer ${PEER} ${PUBIP_ARG} ${MINER_ARG}
Restart=always
RestartSec=10
KillMode=mixed
KillSignal=SIGTERM
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --quiet "${SVC}.service"
systemctl restart "${SVC}.service"
sleep 6
if systemctl is-active --quiet "${SVC}.service"; then
  ok "servicio activo: ${SVC}"
else
  die "el servicio no arrancó — revisa: journalctl -u ${SVC} -n 30"
fi

# 8. Resumen
echo
printf "\033[1;32m═══ Nodo Metriplex corriendo ═══\033[0m\n"
echo "  rol:       $ROLE"
echo "  servicio:  ${SVC}  (systemctl status ${SVC})"
echo "  API:       http://127.0.0.1:${API_PORT}/info"
echo "  P2P:       ${P2P_PORT}   peer: ${PEER}"
if [ "$ROLE" = validator ]; then
  [ -n "$PUBLIC_IP" ] || warn "sin --public-ip: otros nodos no podrán alcanzarte para el registro"
  echo
  printf "\033[1;36m  Para activarte como VALIDADOR:\033[0m\n"
  echo "  1) Envía 100 MPX a tu identidad:  ${IDENTITY:-<ver keystore>}"
  echo "  2) Ejecuta:  bash $NODE_DIR/scripts/register-validator.sh --api-port ${API_PORT}${PUBLIC_IP:+ --public-ip $PUBLIC_IP}"
fi
