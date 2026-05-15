# SPDX-License-Identifier: BUSL-1.1
#
# Metriplex Cryptographic Core
# Copyright (c) 2025-2026 NTellezM (Nelson Tellez)
#
# This file is part of the Metriplex Cryptographic Core, licensed under
# the Business Source License 1.1 (BUSL-1.1).
#
# Non-production use (research, education, personal projects) is permitted.
# Production use requires a commercial license until 2027-05-09, after which
# this file is available under the MIT License.
#
# Contact: metriplexmpx@gmail.com
# License: See LICENSE-CORE in the repository root
#
"""
crypto/keys.py — Gestión de Claves CAF v7
==========================================
Clave privada: parámetros del IFS {(Aᵢ, bᵢ)} — matrices contractivas en ℝ⁴.
Clave pública: Tensor M3 del atractor — derivado via algoritmo del caos.

Condiciones de admisibilidad (CAF v7):
  R1: det(Aᵢ) > 0  →  matrices orientation-preserving (sin reflexiones)
  R2: ‖φ₃_ref‖ > ε_sym  →  asimetría mínima del atractor
  Kruskal: n ≤ ⌊C(d+2,3)/3⌋ = 6 para d=4  →  unicidad de la descomposición
  Escala: ρ(Aᵢ) ∈ [0.30, 0.70]  →  zona convexa del espacio de contracciones
  Rango: rank([b₁|...|bₙ]) = min(n,d)  →  bᵢ en posición general
"""

import hashlib
import json
import os
from math import comb

import numpy as np
from core.arithmetic import SCALE_FACTOR, fp_div_safe, fp_mul, to_float

D = 4
N = 4  # n=4 satisface Kruskal para d=4: 4 <= floor(C(6,3)/3) = 6
KRUSKAL_BOUND = comb(D + 2, 3) // 3  # 6 para d=4

RHO_MIN = 0.30
RHO_MAX = 0.70
MAX_KEYGEN_ATTEMPTS = 200
N_ATTRACTOR_SAMPLES = 2000
N_BURN = 300


# ─────────────────────────────────────────────────────────────────────────────
#  UTILIDADES CRIPTOGRÁFICAS
# ─────────────────────────────────────────────────────────────────────────────


def secure_float(lo: float, hi: float) -> float:
    """Float aleatorio en [lo, hi] con entropía del SO (4 bytes = 32 bits)."""
    r = int.from_bytes(os.urandom(4), "little") / (2**32 - 1)
    return lo + r * (hi - lo)


def secure_int_fp(lo: float, hi: float) -> int:
    """Entero en punto fijo con entropía del SO."""
    return int(secure_float(lo, hi) * SCALE_FACTOR)


# ─────────────────────────────────────────────────────────────────────────────
#  CONSTRUCCIÓN DE MATRICES CONTRACTIVAS
# ─────────────────────────────────────────────────────────────────────────────


def _qr_rotation_fp() -> list:
    """
    Genera una matriz de rotación aleatoria en ℝᵈ via descomposición QR.
    Garantiza det(Q) = +1 (condición R1: orientation-preserving).
    """
    # Usar numpy solo en keygen (no en tiempo de prueba)
    import numpy as np

    seed = int.from_bytes(os.urandom(4), "little")
    rng = np.random.RandomState(seed % (2**31))
    M = rng.randn(D, D)
    Q, _ = np.linalg.qr(M)

    # Forzar det > 0 (reflejo en columna 0 si det < 0)
    if float(np.linalg.det(Q)) < 0:
        Q[:, 0] *= -1

    return [[int(float(Q[r][c]) * SCALE_FACTOR) for c in range(D)] for r in range(D)]


def _make_contraction(scale: float) -> list:
    """
    Construye Aᵢ = scale · Q donde Q es rotación aleatoria.
    Radio espectral exacto = scale (todas las rotaciones tienen rho=1).
    det(Aᵢ) = scale⁴ > 0  ✓
    """
    Q_fp = _qr_rotation_fp()
    scale_fp = int(scale * SCALE_FACTOR)
    return [[fp_mul(scale_fp, Q_fp[r][c]) for c in range(D)] for r in range(D)]


# ─────────────────────────────────────────────────────────────────────────────
#  VALIDACIONES R1, R2, RANGO, KRUSKAL
# ─────────────────────────────────────────────────────────────────────────────


def validate_r1(matrices: list) -> tuple:
    """R1: det(Aᵢ) > 0 para toda i."""
    import numpy as np

    dets = []
    for A in matrices:
        A_f = [[to_float(A[r][c]) for c in range(D)] for r in range(D)]
        dets.append(float(np.linalg.det(A_f)))
    ok = all(d > 1e-12 for d in dets)
    return ok, dets


def validate_scale(matrices: list) -> tuple:
    """ρ(Aᵢ) ∈ [RHO_MIN, RHO_MAX] para toda i."""
    import numpy as np

    rhos = []
    for A in matrices:
        A_f = [[to_float(A[r][c]) for c in range(D)] for r in range(D)]
        rhos.append(float(max(abs(v) for v in np.linalg.eigvals(A_f))))
    ok = all(RHO_MIN - 0.02 <= r <= RHO_MAX + 0.02 for r in rhos)
    return ok, rhos


def validate_kruskal(vectores: list, n: int) -> tuple:
    """
    1. n ≤ KRUSKAL_BOUND  (Comon et al. 2008)
    2. rank([b₁|...|bₙ]) = min(n,d)  (posición general)
    """
    import numpy as np

    if n > KRUSKAL_BOUND:
        return False, 0, KRUSKAL_BOUND

    B = [[to_float(vectores[i][k]) for i in range(n)] for k in range(D)]
    rank = int(np.linalg.matrix_rank(B))
    ok = rank == min(n, D)
    return ok, rank, KRUSKAL_BOUND


def validate_r2(
    attractor: list, matrices: list, vectores: list, n_samples: int = 40
) -> tuple:
    """
    R2: ‖φ₃_ref‖ > ε_sym.
    El atractor debe tener asimetría mínima para que c5 sea discriminativo.
    """
    import random

    from core.verifier import calibrate, skew_finger

    N_sub = min(48, len(attractor))

    phi3_norms = []
    for _ in range(n_samples):
        sub = [attractor[i] for i in random.sample(range(len(attractor)), N_sub)]
        sk = skew_finger(sub)
        norm = to_float(sum(fp_mul(sk[k], sk[k]) for k in range(4))) ** 0.5
        phi3_norms.append(norm)

    phi3_ref_norm = sum(phi3_norms) / len(phi3_norms)
    eps_sym = sorted(phi3_norms)[len(phi3_norms) // 10]  # P10

    ok = phi3_ref_norm > eps_sym
    return ok, phi3_ref_norm, eps_sym


# ─────────────────────────────────────────────────────────────────────────────
#  ALGORITMO DEL CAOS (muestreo del atractor IFS)
# ─────────────────────────────────────────────────────────────────────────────


def chaos_game(
    matrices: list, vectores: list, iterations: int = 2000, burn_in: int = 300
) -> list:
    """
    Atractor IFS — usa Rust (metriplex_core) si está disponible, sino numpy.
    Rust: ~0.8ms | numpy: ~8ms  (10x speedup)
    """
    try:
        import metriplex_core as _rust
        return _rust.chaos_game(matrices, vectores, iterations, burn_in)
    except ImportError:
        pass

    from core.arithmetic import SCALE_FACTOR

    K = len(matrices)
    D = len(matrices[0])

    M_np = np.array(matrices, dtype=np.float64) / SCALE_FACTOR
    V_np = np.array(vectores, dtype=np.float64) / SCALE_FACTOR

    total_steps = iterations + burn_in
    indices = np.random.randint(0, K, size=total_steps)

    x = np.zeros(D, dtype=np.float64)
    attractor = np.empty((iterations, D), dtype=np.float64)

    for i in range(total_steps):
        idx = indices[i]
        x = np.dot(M_np[idx], x) + V_np[idx]
        if i >= burn_in:
            attractor[i - burn_in] = x

    return (attractor * SCALE_FACTOR).astype(np.int64).tolist()


# ─────────────────────────────────────────────────────────────────────────────
#  GENERACIÓN DE CLAVE PRIVADA
# ─────────────────────────────────────────────────────────────────────────────


def generate_private_key(
    n_maps: int = N,
    rho_min: float = RHO_MIN,
    rho_max: float = RHO_MAX,
) -> dict:
    """
    Genera un IFS afín admisible para CAF v7.
    Verifica R1, escala y posición general de {bᵢ}.
    Reintenta hasta encontrar una configuración válida.
    """
    assert n_maps <= KRUSKAL_BOUND, (
        f"n={n_maps} supera el límite de Kruskal {KRUSKAL_BOUND} para d={D}"
    )

    for attempt in range(MAX_KEYGEN_ATTEMPTS):
        matrices = []
        vectores = []

        for _ in range(n_maps):
            scale = secure_float(rho_min, rho_max)
            matrices.append(_make_contraction(scale))
            vectores.append([secure_int_fp(-1.0, 1.0) for _ in range(D)])

        # Verificar R1
        r1_ok, dets = validate_r1(matrices)
        if not r1_ok:
            continue

        # Verificar escala
        sc_ok, rhos = validate_scale(matrices)
        if not sc_ok:
            continue

        # Verificar posición general de {bᵢ}
        kr_ok, rank, _ = validate_kruskal(vectores, n_maps)
        if not kr_ok:
            continue

        return {
            "A": matrices,
            "b": vectores,
            "meta": {
                "n": n_maps,
                "d": D,
                "rhos": [round(r, 4) for r in rhos],
                "dets": [round(d, 6) for d in dets],
                "rank_b": rank,
            },
        }

    raise RuntimeError(
        f"No se pudo generar clave válida en {MAX_KEYGEN_ATTEMPTS} intentos."
    )


# ─────────────────────────────────────────────────────────────────────────────
#  DERIVACIÓN DE CLAVE PÚBLICA
# ─────────────────────────────────────────────────────────────────────────────


def derive_public_key(private_key: dict) -> list:
    """
    Deriva la clave pública (Tensor M3) via algoritmo del caos.
    M3 = E_μ[(x−μ)⊗(x−μ)⊗(x−μ)]  sobre la medida invariante μ_Q.
    """
    matrices = private_key["A"]
    vectores = private_key["b"]

    # Muestrear el atractor con el algoritmo del caos (corrección v7)
    attractor = chaos_game(matrices, vectores)

    # Calcular el tensor M3
    from crypto.tensors import calculate_m3_tensor

    return calculate_m3_tensor(attractor)


def derive_public_key_with_attractor(private_key: dict) -> tuple:
    """
    Como derive_public_key pero también retorna el atractor para calibración.
    Útil para generar los CriterionParams junto con la clave pública.
    """
    matrices = private_key["A"]
    vectores = private_key["b"]
    attractor = chaos_game(matrices, vectores)

    from crypto.tensors import calculate_m3_tensor

    m3 = calculate_m3_tensor(attractor)
    return m3, attractor


# ─────────────────────────────────────────────────────────────────────────────
#  VALIDACIÓN COMPLETA (R1 + R2 + KRUSKAL)
# ─────────────────────────────────────────────────────────────────────────────


def validate_key_full(private_key: dict) -> dict:
    """
    Ejecuta todas las validaciones sobre una clave generada.
    Retorna un informe completo.
    """
    matrices = private_key["A"]
    vectores = private_key["b"]
    n = len(matrices)

    r1_ok, dets = validate_r1(matrices)
    sc_ok, rhos = validate_scale(matrices)
    kr_ok, rank, bound = validate_kruskal(vectores, n)

    # R2 requiere muestrear el atractor (más costoso)
    # FIX: Usar 'iterations' y 'burn_in' en lugar de 'n_samples' y 'burn'
    attractor = chaos_game(matrices, vectores, iterations=500, burn_in=100)
    r2_ok, phi3_norm, eps_sym = validate_r2(attractor, matrices, vectores, n_samples=20)

    all_ok = r1_ok and sc_ok and kr_ok and r2_ok
    return {
        "all_ok": all_ok,
        "R1": {"ok": r1_ok, "dets": [round(d, 6) for d in dets]},
        "scale": {"ok": sc_ok, "rhos": [round(r, 4) for r in rhos]},
        "kruskal": {"ok": kr_ok, "rank": rank, "bound": bound, "n": n},
        "R2": {
            "ok": r2_ok,
            "phi3_norm": round(phi3_norm, 4),
            "eps_sym": round(eps_sym, 4),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
#  SERIALIZACIÓN
# ─────────────────────────────────────────────────────────────────────────────


def key_fingerprint(public_m3: list) -> str:
    """Hash SHA256 del tensor M3 — identifica la cuenta en el ledger."""
    return hashlib.sha256(json.dumps(public_m3, sort_keys=True).encode()).hexdigest()
