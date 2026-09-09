# SPDX-License-Identifier: MIT
"""
Modelo de emisión — ÚNICA fuente de verdad para la recompensa de coinbase.

Tanto el productor (network/miner.py) como el verificador (blockchain/chain.py)
llaman a expected_coinbase_reward(), garantizando que computan exactamente el
mismo valor (requisito de consenso). Extraído de AutoMiner para poder validar
la coinbase a nivel de bloque.
"""
import math
import hashlib
import json

from core.arithmetic import SCALE_FACTOR
from blockchain.validator_registry import LAMBDA_MIN, LAMBDA_MAX

T_SCALE = 7_063_101
LAMBDA_MEAN_INIT = -0.6185
TARGET_SUPPLY_MPX = 21_000_000
SUPPLY_PER_LAMBDA = TARGET_SUPPLY_MPX / abs(LAMBDA_MEAN_INIT)

# Altura desde la cual se valida la coinbase a nivel de bloque (monto/unicidad).
# Los bloques anteriores (era de 50 MPX, faucet, bug de emisión) se aceptan bajo
# reglas legacy. Se fija en el despliegue coordinado.
COINBASE_ACTIVATION = 10**12  # placeholder; el deploy la ajusta


def _active_pairs(registry):
    """(lambda, m3_hash) de los validadores activos, misma lógica que AutoMiner."""
    excluded = getattr(registry, "EXCLUDED_VALIDATORS", set())
    return [
        (v["lambda_value"], m3h)
        for m3h, v in registry.validators.items()
        if v.get("lambda_value") is not None
        and v.get("active", True)
        and m3h not in excluded
    ]


def lambda_mean(registry) -> float:
    lams = [l for l, _ in _active_pairs(registry)]
    return sum(lams) / len(lams) if lams else LAMBDA_MEAN_INIT


def voronoi_fraction(registry, m3_hash: str) -> float:
    """Territorio Voronoi del validador `m3_hash` en el eje λ. Idéntico a
    AutoMiner._get_voronoi_fraction pero parametrizado por identidad."""
    active = _active_pairs(registry)
    if not active:
        return 1.0
    my_lambda = None
    if m3_hash:
        for lam, m3h in active:
            if m3h.startswith(m3_hash[:8]) or m3_hash.startswith(m3h[:8]):
                my_lambda = lam
                break
    if my_lambda is None:
        return 1.0 / max(len(active), 1)
    lambdas = sorted(set(lam for lam, _ in active))
    i = lambdas.index(my_lambda)
    left = LAMBDA_MIN if i == 0 else (lambdas[i - 1] + my_lambda) / 2
    right = LAMBDA_MAX if i == len(lambdas) - 1 else (my_lambda + lambdas[i + 1]) / 2
    frac = (right - left) / (LAMBDA_MAX - LAMBDA_MIN)
    return max(0.0, min(1.0, frac))


def expected_coinbase_reward(registry, block_index: int, leader_m3_hash: str) -> int:
    """Recompensa raw esperada para la coinbase del bloque `block_index` cuyo
    líder (receptor) es `leader_m3_hash`. Mismo cómputo que el minero."""
    lm = lambda_mean(registry)
    r0_raw = SUPPLY_PER_LAMBDA * lm ** 2 / T_SCALE * SCALE_FACTOR
    r_base = r0_raw * math.exp(lm * block_index / T_SCALE)
    frac = voronoi_fraction(registry, leader_m3_hash)
    return int(r_base * frac)


def m3_hash(m3) -> str:
    return hashlib.sha256(
        json.dumps(m3, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
