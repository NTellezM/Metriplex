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
    Retorna un array 3D de dimensiones D x D x D.
    """
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