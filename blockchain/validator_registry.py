# SPDX-License-Identifier: MIT
#
# Metriplex Protocol
# Copyright (c) 2025-2026 NTellezM (Nelson Tellez)
#
"""
blockchain/validator_registry.py — Fractal Validator Registry (FVR)
====================================================================
Mantiene el set global de validadores reconstruido desde genesis.
La identidad de cada validador es su tensor M3 — no una clave arbitraria.

Tipos de TX soportados (via payload.op):
  VALIDATOR_REGISTER  — ingreso al set
  VALIDATOR_EXIT      — salida voluntaria + release de stake
  VALIDATOR_SLASH     — penalización por double-sign (futura)
"""
import hashlib
import json


VALIDATOR_STAKE_REQUIRED = 100 * 1073741824  # 100 MPX en CAF scale
VALIDATOR_REGISTER_OP    = "VALIDATOR_REGISTER"
VALIDATOR_EXIT_OP        = "VALIDATOR_EXIT"
VALIDATOR_SLASH_OP       = "VALIDATOR_SLASH"


def _hash_m3(m3: list) -> str:
    return hashlib.sha256(
        json.dumps(m3, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class ValidatorRegistry:
    """
    Registry on-chain de validadores activos.
    Se reconstruye desde genesis al iniciar el nodo.
    """

    def __init__(self):
        self.validators: dict[str, dict] = {}
        # m3_hash → {m3, endpoint, stake, registered_at, slashed}
        self.slashed: set[str] = set()

    # ── Procesamiento de TXs ───────────────────────────────────────────────

    def process_tx(self, tx, block_index: int):
        """
        Procesa una TX y actualiza el registry si corresponde.
        Llamado por Blockchain.add_block y load_chain_from_disk.
        """
        payload = tx.payload if hasattr(tx, "payload") else {}
        if not payload:
            return

        op = payload.get("op")

        if op == VALIDATOR_REGISTER_OP:
            self._register(tx, block_index)
        elif op == VALIDATOR_EXIT_OP:
            self._exit(tx, block_index)
        elif op == VALIDATOR_SLASH_OP:
            self._slash(payload.get("target_m3_hash"), block_index)

    def _register(self, tx, block_index: int):
        m3 = tx.sender_m3
        if not m3:
            return

        m3_hash = _hash_m3(m3)

        if m3_hash in self.slashed:
            print(f"[FVR] Registro rechazado: M3 {m3_hash[:8]} está slasheado.")
            return

        if m3_hash in self.validators:
            print(f"[FVR] Registro ignorado: M3 {m3_hash[:8]} ya está registrado.")
            return

        if tx.amount < VALIDATOR_STAKE_REQUIRED:
            print(f"[FVR] Registro rechazado: stake insuficiente ({tx.amount} < {VALIDATOR_STAKE_REQUIRED}).")
            return

        endpoint = tx.payload.get("endpoint", "")
        self.validators[m3_hash] = {
            "m3":            m3,
            "m3_hash":       m3_hash,
            "endpoint":      endpoint,
            "stake":         tx.amount,
            "registered_at": block_index,
            "slashed":       False,
        }
        print(f"[FVR] ✅ Validador registrado: {m3_hash[:8]}... endpoint={endpoint} bloque={block_index}")

    def _exit(self, tx, block_index: int):
        m3_hash = _hash_m3(tx.sender_m3) if tx.sender_m3 else None
        if m3_hash and m3_hash in self.validators:
            del self.validators[m3_hash]
            print(f"[FVR] Validador {m3_hash[:8]} salió del set en bloque {block_index}.")

    def _slash(self, target_m3_hash: str, block_index: int):
        if not target_m3_hash:
            return
        if target_m3_hash in self.validators:
            del self.validators[target_m3_hash]
        self.slashed.add(target_m3_hash)
        print(f"[FVR] ⚡ Validador {target_m3_hash[:8]} slasheado en bloque {block_index}.")

    # ── Consultas ──────────────────────────────────────────────────────────

    def get_sorted_validators(self) -> list[dict]:
        """
        Retorna el set ordenado por m3_hash — determinístico y global.
        Todos los nodos producen el mismo array dado el mismo historial.
        """
        return sorted(self.validators.values(), key=lambda v: v["m3_hash"])

    def get_endpoints(self) -> list[str]:
        return [v["endpoint"] for v in self.validators.values() if v["endpoint"]]

    def is_validator(self, m3: list) -> bool:
        return _hash_m3(m3) in self.validators

    def is_slashed(self, m3: list) -> bool:
        return _hash_m3(m3) in self.slashed

    def size(self) -> int:
        return len(self.validators)

    def __repr__(self):
        entries = [f"  {v['m3_hash'][:8]}... ep={v['endpoint']} stake={v['stake']//1073741824}MPX"
                   for v in self.get_sorted_validators()]
        return "ValidatorRegistry[\n" + "\n".join(entries) + "\n]"
