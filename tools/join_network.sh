#!/bin/bash
# Metriplex — Join Network Script
# Uso: bash join_network.sh --password PASS --api-port 8003 --p2p-port 65436 --public-ip 1.2.3.4

set -e

PASSWORD=""
API_PORT="8003"
P2P_PORT="65436"
PUBLIC_IP=""
BASE_DIR="/opt/Metriplex"
GENESIS_PEER="157.180.113.24:65432"

while [[ $# -gt 0 ]]; do
    case $1 in
        --password)  PASSWORD="$2";  shift 2 ;;
        --api-port)  API_PORT="$2";  shift 2 ;;
        --p2p-port)  P2P_PORT="$2";  shift 2 ;;
        --public-ip) PUBLIC_IP="$2"; shift 2 ;;
        *) echo "Argumento desconocido: $1"; exit 1 ;;
    esac
done

DB_FILE="node_data_${API_PORT}.db"
KEYSTORE="keystore_node_${P2P_PORT}.json"
SERVICE_NAME="metriplex-node-${P2P_PORT}"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  METRIPLEX JOIN NETWORK"
echo "  API:$API_PORT  P2P:$P2P_PORT  IP:$PUBLIC_IP"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# PASO 1 — Python 3.12
echo "[1/6] Verificando Python 3.12..."
if ! python3.12 --version &>/dev/null; then
    add-apt-repository ppa:deadsnakes/ppa -y && apt update -q
    apt install -y python3.12 python3.12-venv python3.12-dev
fi
echo "  ✓ $(python3.12 --version)"

# PASO 2 — venv
echo "[2/6] Configurando venv Python 3.12..."
cd $BASE_DIR
PYVER=$(venv/bin/python3 --version 2>&1 || echo "none")
if [[ "$PYVER" != *"3.12"* ]]; then
    rm -rf venv && python3.12 -m venv venv
fi
source venv/bin/activate
pip install -q -r requirements.txt && pip install -q httpx
echo "  ✓ venv listo"

# PASO 3 — Bootstrap
echo "[3/6] Descargando snapshot..."
[ ! -f "$BASE_DIR/$DB_FILE" ] && bash $BASE_DIR/bootstrap.sh $DB_FILE || echo "  DB existente — omitiendo"

# PASO 4 — Keystore
echo "[4/6] Generando keystore..."
if [ ! -f "$BASE_DIR/$KEYSTORE" ]; then
python3 - << PYEOF
import sys
sys.path.insert(0, '$BASE_DIR')
from crypto.keys import generate_private_key, derive_public_key_with_attractor
from crypto.keystore import save_keystore
from core.verifier import calibrate, evaluate, CriterionParams
import numpy as np

for attempt in range(50):
    priv = generate_private_key()
    pub, att = derive_public_key_with_attractor(priv)
    params = calibrate(att, priv['A'], priv['b'], N=2000)
    params_dict = params.__dict__ if hasattr(params,'__dict__') else dict(params._asdict())
    result = evaluate(att, priv['A'], priv['b'], CriterionParams(**params_dict), 2000)
    if result.pass_all:
        save_keystore('$PASSWORD', priv, pub, params_dict, att, '$BASE_DIR/$KEYSTORE')
        lam = sum(np.log(max(abs(np.linalg.eigvals([[priv['A'][i][r][c]/1073741824 for c in range(4)] for r in range(4)])))) for i in range(4))/4
        print(f'  ✓ Keystore generado — lambda={lam:.6f}')
        break
else:
    print('ERROR: no se pudo generar keystore válido'); sys.exit(1)
PYEOF
else
    echo "  Keystore existente — omitiendo"
fi

# PASO 5 — Servicio systemd
echo "[5/6] Creando servicio systemd..."
cat > /etc/systemd/system/${SERVICE_NAME}.service << SVCEOF
[Unit]
Description=Metriplex Node (port ${P2P_PORT})
After=network.target
[Service]
Type=simple
User=root
WorkingDirectory=${BASE_DIR}
Environment="MINER_PASSWORD=${PASSWORD}"
Environment="NODE_DATA_DIR=${BASE_DIR}"
ExecStart=${BASE_DIR}/venv/bin/python3 -u main.py --p2p-port ${P2P_PORT} --api-port ${API_PORT} --public-ip ${PUBLIC_IP} --miner-wallet ${KEYSTORE} --peer ${GENESIS_PEER}
Restart=always
RestartSec=10
[Install]
WantedBy=multi-user.target
SVCEOF
systemctl daemon-reload && systemctl enable ${SERVICE_NAME}
echo "  ✓ Servicio ${SERVICE_NAME} creado"

# PASO 6 — Arrancar
echo "[6/6] Arrancando nodo..."
systemctl start ${SERVICE_NAME} && sleep 8
systemctl is-active --quiet ${SERVICE_NAME} && echo "  ✓ Nodo activo" || { journalctl -u ${SERVICE_NAME} --no-pager | tail -10; exit 1; }

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✓ NODO LISTO — logs: journalctl -u ${SERVICE_NAME} -f"
echo ""
echo "  Para registrarte como validador:"
echo "  1. Pide 100 MPX al admin (bdb8c1f4)"
echo "  2. cd ${BASE_DIR} && source venv/bin/activate"
echo "  3. python3 tools/register_validator.py \\"
echo "       --keystore ${KEYSTORE} --password ${PASSWORD} \\"
echo "       --endpoint ${PUBLIC_IP}:${P2P_PORT} \\"
echo "       --api http://localhost:${API_PORT}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
