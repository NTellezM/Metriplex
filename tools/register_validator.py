#!/usr/bin/env python3
"""
Metriplex — Register Validator
Registra un nodo como validador en el FVR.

Uso:
    python3 tools/register_validator.py \
        --keystore keystore_node_65436.json \
        --password 123 \
        --endpoint 5.78.209.5:65436 \
        --api http://localhost:8003
"""
import argparse, hashlib, json, sys, numpy as np, requests
sys.path.insert(0, '/opt/Metriplex')
from crypto.keystore import load_keystore
from crypto.signatures import sign_transaction
from core.verifier import CriterionParams

parser = argparse.ArgumentParser()
parser.add_argument('--keystore',  required=True)
parser.add_argument('--password',  required=True)
parser.add_argument('--endpoint',  required=True)
parser.add_argument('--api',       default='http://localhost:8003')
args = parser.parse_args()

priv, pub, params, att = load_keystore(args.password, args.keystore)
if hasattr(params, '__dict__'):
    params_dict = params.__dict__
elif hasattr(params, '_asdict'):
    params_dict = params._asdict()
else:
    params_dict = dict(params)
params_obj = CriterionParams(**params_dict)

m3_hash = hashlib.sha256(json.dumps(pub, sort_keys=True, separators=(',',':')).encode()).hexdigest()
lam = sum(np.log(max(abs(np.linalg.eigvals([[priv['A'][i][r][c]/1073741824 for c in range(4)] for r in range(4)])))) for i in range(4)) / 4

print(f"Validador: {m3_hash[:8]}  λ={lam:.6f}  endpoint={args.endpoint}")

# Verificar balance
try:
    bal = requests.get(f"{args.api}/balance/{m3_hash[:8]}", timeout=5).json()
    balance = bal.get('balance_caf', 0)
    print(f"Balance:   {balance} MPX")
    if balance < 100:
        print(f"ERROR: balance insuficiente ({balance} MPX). Necesitas 100 MPX para el stake.")
        sys.exit(1)
except Exception as e:
    print(f"WARNING: no se pudo verificar balance — {e}")

STAKE = 100 * 1073741824

payload = {
    'op': 'VALIDATOR_REGISTER',
    'contraction_matrices': priv['A'],
    'endpoint': args.endpoint,
    'lambda_value': lam,
}

payload_for_signing = {
    'sender_m3': pub, 'receiver_m3': pub,
    'amount': STAKE, 'fee': 0, 'payload': None
}

sig = sign_transaction(priv, payload_for_signing, pub, criterion_params=params_obj, attractor=att)

tx = {
    'sender_m3': pub, 'receiver_m3': pub,
    'amount': STAKE, 'fee': 0,
    'signature_data': sig,
    'payload': payload
}

res = requests.post(f"{args.api}/transaction", json=tx, timeout=10)
print(f"Respuesta: {res.status_code} {res.text}")
