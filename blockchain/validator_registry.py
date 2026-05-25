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
        contraction_matrices = tx.payload.get("contraction_matrices", None)

        # Lyapunov diversity check — solo si el registro incluye matrices
        lambda_value = None
        if contraction_matrices:
            try:
                lambda_value = compute_lambda(contraction_matrices)
                registered_lambdas = [
                    v["lambda_value"] for v in self.validators.values()
                    if v.get("lambda_value") is not None
                ]
                ok, reason = check_geometric_diversity(lambda_value, registered_lambdas)
                if not ok:
                    print(f"[FVR] Registro rechazado: diversidad geométrica insuficiente — {reason}")
                    return
                print(f"[FVR] λ verificado: {lambda_value:.6f}")
            except Exception as e:
                print(f"[FVR] Warning: no se pudo calcular λ — {e}")
                lambda_value = None

        self.validators[m3_hash] = {
            "m3":                   m3,
            "m3_hash":              m3_hash,
            "endpoint":             endpoint,
            "stake":                tx.amount,
            "registered_at":        block_index,
            "slashed":              False,
            "lambda_value":         lambda_value,  # None = validador legacy
            "contraction_matrices": contraction_matrices,
        }
        legacy = " (legacy — sin restricción λ)" if lambda_value is None else f" λ={lambda_value:.4f}"
        print(f"[FVR] ✅ Validador registrado: {m3_hash[:8]}... endpoint={endpoint} bloque={block_index}{legacy}")

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


# ── Lyapunov Consensus — Geometric Diversity ──────────────────────────────

SCALE_FACTOR = 2 ** 30
LAMBDA_MIN   = -1.2039728  # log(0.30)
LAMBDA_MAX   = -0.3566749  # log(0.70)
N_TARGET     = 100         # capacidad objetivo de validadores
D_MIN        = (LAMBDA_MAX - LAMBDA_MIN) / N_TARGET  # ≈ 0.00847


def compute_lambda(contraction_matrices: list) -> float:
    """
    Calcula el exponente de Lyapunov medio del IFS.
    λ(W) = (1/n) Σᵢ log ρ(Aᵢ)
    Complejidad: O(n) donde n = número de mapas (n=4 en producción).
    """
    import numpy as np
    radii = [
        float(np.max(np.abs(np.linalg.eigvals(
            np.array(A, dtype=float) / SCALE_FACTOR
        ))))
        for A in contraction_matrices
    ]
    import math
    return sum(math.log(r) for r in radii) / len(radii)


def check_geometric_diversity(new_lambda: float,
                               registered_lambdas: list,
                               d_min: float = D_MIN) -> tuple:
    """
    Verifica que new_lambda está a distancia mínima d_min
    de todos los lambdas registrados.
    Retorna (bool, str).
    """
    if not (LAMBDA_MIN <= new_lambda <= LAMBDA_MAX):
        return False, f"lambda {new_lambda:.6f} fuera de rango [{LAMBDA_MIN:.4f}, {LAMBDA_MAX:.4f}]"

    if not registered_lambdas:
        return True, "ok"

    min_dist = min(abs(new_lambda - lv) for lv in registered_lambdas)
    if min_dist < d_min:
        return False, f"lambda demasiado cercano a validador existente (dist={min_dist:.6f} < {d_min:.6f})"

    return True, "ok"
