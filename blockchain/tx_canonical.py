# SPDX-License-Identifier: MIT
"""
Serialización canónica ÚNICA del mensaje firmado de una transacción normal.

El cliente (metriplex-crypto.js buildSignedTx), el relayer, wallet_cli, el
mempool (vía validate_transaction) y la cadena deben producir EXACTAMENTE este
hash, o una firma válida en un punto fallaría en otro. El payload NO se firma
(se transporta, p.ej. el timestamp): payload=None siempre.

Las operaciones de protocolo (VALIDATOR_*) usan otra serialización dedicada
(blockchain.protocol_auth.protocol_op_hash), no ésta.
"""
import hashlib
import json


def canonical_tx_hash(sender_m3, receiver_m3, amount, fee) -> str:
    payload_dict = {
        "sender_m3":   sender_m3,
        "receiver_m3": receiver_m3,
        "amount":      amount,
        "fee":         fee,
        "payload":     None,
    }
    return hashlib.sha256(
        json.dumps(payload_dict, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
