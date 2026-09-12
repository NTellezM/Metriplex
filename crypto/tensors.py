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
Módulo de cálculo tensorial para el protocolo CAF.
Genera y manipula el tensor de tercer orden M3 que actúa como
llave pública o identificador criptográfico del atractor.
"""

from core.arithmetic import fp_mul, fp_div_safe, SCALE_FACTOR

D = 4

try:
    import metriplex_core as _rust
    USING_RUST = True
except ImportError:  # pragma: no cover
    _rust = None
    USING_RUST = False


class TensorBackendError(RuntimeError):
    """El backend de referencia (Rust) no esta disponible."""


def require_rust(contexto: str) -> None:
    """Aborta si falta la extension Rust.

    El fallback Python de calculate_m3_tensor NO coincide con la extension:
    sobre la misma entrada difieren hasta 3,3e8, el 7800% de la magnitud del
    tensor. Rust es la referencia (reproduce el public_m3 con error 0).

    Degradarse en silencio produce dos fallos graves y dificiles de
    diagnosticar: un nodo que valida distinto al resto queda fuera de consenso
    desde ZK_TOLERANCE_ACTIVATION, y un keystore creado con el fallback lleva
    una clave publica que la red no puede reproducir, de modo que su saldo
    queda inmovilizado. Mejor fallar aqui, ruidosamente.
    """
    if USING_RUST:
        return
    raise TensorBackendError(
        f"metriplex_core (extension Rust) no esta instalado y {contexto} lo "
        f"requiere.\n"
        f"El fallback Python calcula tensores distintos y NO sirve para "
        f"consenso ni para crear claves.\n"
        f"Instalar desde la raiz del repo:\n"
        f"    pip install -r requirements.txt\n"
        f"o directamente:\n"
        f"    pip install ./rust_core   (requiere cargo/rustc)"
    )


def calculate_centroid(x_points: list[list[int]]) -> list[int]:
    """Calcula el centroide mu (media espacial) del conjunto de puntos."""
    N = len(x_points)
    mu = [0] * D
    for i in range(N):
        for k in range(D):
            mu[k] += x_points[i][k]
            
    for k in range(D):
        mu[k] = fp_div_safe(mu[k], N * SCALE_FACTOR)
    return mu

def calculate_m3_tensor(x_points: list[list[int]]) -> list[list[list[int]]]:
    """
    Construye el tensor simétrico M3 en formato de punto fijo.
    M3_ijk = (1/N) * sum((x_i - mu_i) * (x_j - mu_j) * (x_k - mu_k))
    Rust: ~0.6ms | Python: ~85ms  (136x speedup)
    """
    if USING_RUST:
        return _rust.calculate_m3_tensor(x_points)
    N = len(x_points)
    mu = calculate_centroid(x_points)
    
    # Inicializar tensor M3 (DxDxD) con ceros
    m3 = [[[0 for _ in range(D)] for _ in range(D)] for _ in range(D)]
    
    for p in range(N):
        # Vector centrado: (x - mu)
        x_centered = [x_points[p][d] - mu[d] for d in range(D)]
        
        # Producto tensorial de orden 3
        for i in range(D):
            for j in range(D):
                # Cálculo intermedio para no perder precisión prematuramente
                term_ij = fp_mul(x_centered[i], x_centered[j])
                for k in range(D):
                    term_ijk = fp_mul(term_ij, x_centered[k])
                    m3[i][j][k] += term_ijk
                    
    # Promediar dividiendo por N
    n_fp = N * SCALE_FACTOR
    for i in range(D):
        for j in range(D):
            for k in range(D):
                m3[i][j][k] = fp_div_safe(m3[i][j][k], n_fp)
                
    return m3