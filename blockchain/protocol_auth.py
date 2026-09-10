# SPDX-License-Identifier: MIT
"""
Autorización de operaciones de protocolo (registro/salida/actualización de
validadores y gobernanza).

Hasta PROTOCOL_SIG_ACTIVATION, estas operaciones se aceptaban sin verificar
firma ni saldo (reglas legacy). A partir de esa altura se exige:

  * firma ZK del emisor sobre un mensaje CANÓNICO por operación (liga la firma
    al op y a sus campos, evitando replay/malleability), y
  * para VALIDATOR_REGISTER, saldo real >= stake.

El mensaje canónico es determinista e idéntico en emisor y verificador, así que
todos los nodos validan igual (requisito de consenso).
"""
import hashlib
import json

# Altura desde la cual las reglas estrictas están activas. Los bloques
# anteriores se validan con las reglas legacy para que el replay histórico no
# se rompa. Debe estar unos bloques por delante del despliegue coordinado.
PROTOCOL_SIG_ACTIVATION = 107342  # despliegue coordinado 2026-09-09

PROTOCOL_OPS = frozenset({
    "VALIDATOR_REGISTER",
    "VALIDATOR_EXIT",
    "VALIDATOR_UPDATE",
    "VALIDATOR_GOVERNANCE_EXIT",
})


def _sha(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def protocol_op_hash(sender_m3, payload: dict, amount: int, receiver_m3=None, fee: int = 0) -> str:
    """Mensaje canónico que firma el emisor de una operación de protocolo.

    Incluye el op y los campos que autorizan la acción, para que una firma de
    un op no sea reutilizable como otro ni con otros parámetros.
    """
    op = payload.get("op")
    canonical = {
        "op": op,
        "sender_m3": sender_m3,
        "amount": int(amount or 0),
        "endpoint": payload.get("endpoint", ""),
        "target_m3_hash": payload.get("target_m3_hash", ""),
    }
    if payload.get("version") == 2:
        from blockchain.rules import CHAIN_ID
        canonical = {
            "chain_id": CHAIN_ID,
            "sender_m3": sender_m3,
            "receiver_m3": receiver_m3,
            "amount": int(amount or 0),
            "fee": int(fee or 0),
            "payload": payload,
        }
    return _sha(canonical)


def governance_vote_hash(target_m3_hash: str) -> str:
    """Mensaje que firma cada validador al votar una expulsión de gobernanza."""
    return _sha({"vote": "VALIDATOR_GOVERNANCE_EXIT", "target": target_m3_hash})


def verify_vote_signature(sig: dict, voter_m3: list, vote_hash: str) -> bool:
    """Verifica la prueba ZK de un voto de gobernanza contra el M3 del votante.

    Espeja el 'modo compacto' de Blockchain._verify_signature: la prueba lleva
    sus criterion_params y el ZK la liga al M3 del votante y al mensaje del voto.
    """
    try:
        from crypto.zkp import ZKEngine
        from core.verifier import CriterionParams
        if not isinstance(sig, dict) or "criterion_params" not in sig:
            return False
        params = CriterionParams.from_dict(sig["criterion_params"])
        return ZKEngine.verify_proof(
            proof=sig, public_m3=voter_m3, tx_hash=vote_hash,
            criterion_params=params, N_total=2000,
        )
    except Exception:
        return False
