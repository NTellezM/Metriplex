#!/usr/bin/env python3
import sys, json, requests
sys.path.insert(0, '/opt/Metriplex')

from crypto.keystore import load_keystore
from crypto.signatures import sign_transaction
from core.verifier import CriterionParams

TARGET = "ee481176779ed17cfeccfcdae05ea97daacfa8b6ec5321348c5e4119462cea6e"
PASSWORD = "123"
API = "http://localhost:8000"

# Obtener m3_hash completos desde el registry
validators = requests.get(f"{API}/validators").json()
vlist = validators.get('validators', validators)

KEYSTORES = {
    'keystore_node0.json': 'bdb8c1f4',
    'keystore_node2.json': '3542268a',
}

votes = []
for ks_file, prefix in KEYSTORES.items():
    # Buscar hash completo en registry
    v = next((v for v in vlist if v['m3_hash'].startswith(prefix)), None)
    if not v:
        print(f"ERROR: {prefix} no encontrado en registry")
        continue
    full_hash = v['m3_hash']
    print(f"Cargando {ks_file} → {full_hash[:8]}...")
    priv, pub, params, att = load_keystore(PASSWORD, f'/opt/Metriplex/{ks_file}')
    params_obj = CriterionParams(**params)
    payload_for_signing = {'sender_m3': pub, 'receiver_m3': pub, 'amount': 0, 'fee': 0, 'payload': None}
    sig = sign_transaction(priv, payload_for_signing, pub, criterion_params=params_obj, attractor=att)
    votes.append({'m3_hash': full_hash, 'signature': sig})
    print(f"  Voto de {full_hash[:8]} agregado ✓")

print(f"\nVotos: {len(votes)} — requeridos: 2")

# Emitir TX desde node-0
priv0, pub0, params0, att0 = load_keystore(PASSWORD, '/opt/Metriplex/keystore_node0.json')
params_obj0 = CriterionParams(**params0)
payload = {'op': 'VALIDATOR_GOVERNANCE_EXIT', 'target_m3_hash': TARGET, 'votes': votes}
payload_for_signing = {'sender_m3': pub0, 'receiver_m3': pub0, 'amount': 0, 'fee': 1, 'payload': None}
sig0 = sign_transaction(priv0, payload_for_signing, pub0, criterion_params=params_obj0, attractor=att0)
tx = {
    'sender_m3': pub0, 'receiver_m3': pub0, 'amount': 0, 'fee': 1,
    'signature_data': sig0,
    'payload': payload
}
print(f"Emitiendo TX GOVERNANCE_EXIT para {TARGET[:8]}...")
res = requests.post(f'{API}/transaction', json=tx)
print(f"Status: {res.status_code}")
print(res.text)
