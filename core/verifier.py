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
core/verifier.py — Criterio de Convergencia Compuesto CAF v7
============================================================
c1: Δ_AS < θ_IFS            (auto-similaridad, pushforward ponderado)
c2: Var(φ̂) > σ²_min         (anti-concentración)
c3: N_act / N > 0.50         (completitud)
c4: [DEPRECATED v3] Originally measured third-moment skewness of φ̂.
    Removed in protocol iteration v3 (2025) after empirical analysis
    showed c4 was redundant with c5 under the calibrated threshold
    regime. The packed bit field preserves the c1-c8 numbering for
    backward compatibility; c4's bit position (bit 3) is reserved=0.
c5: ‖φ₃(μ̂) − φ₃_ref‖ < τ  (huella de asimetría — absorbs c4 function)
c6: μ₂(d_pairs) > d²_min    (dispersión de pares, grado 2)
c7: ε_μ < θ_μ                (invariancia de la media)
c8: P₅/μ(d_pares) > thresh  (ratio min/media)
"""

import numpy as np

from core.arithmetic import SCALE_FACTOR, fp_div_safe, fp_mul, to_float

D = 4
SQRT2_FP = int(1.41421356 * SCALE_FACTOR)


# ── φ(x): mapa de características (15 componentes para d=4) ──────────────────


def phi(x):
    feats = [SCALE_FACTOR]
    for i in range(D):
        feats.append(fp_mul(SQRT2_FP, x[i]))
    for i in range(D):
        for j in range(i, D):
            if i == j:
                feats.append(fp_mul(x[i], x[i]))
            else:
                feats.append(fp_mul(SQRT2_FP, fp_mul(x[i], x[j])))
    return feats  # 15 componentes


def phi_mean(pts):
    N = len(pts)
    nf = len(phi(pts[0]))
    acc = [0] * nf
    for p in pts:
        ph = phi(p)
        for k in range(nf):
            acc[k] += ph[k]
    nfp = N * SCALE_FACTOR
    return [fp_div_safe(acc[k], nfp) for k in range(nf)]


# ── c1: Δ_AS con pushforward ponderado sobre TODOS los mapas ─────────────────


def delta_AS(pts, matrices, vectores, probs=None):
    n = len(matrices)
    if probs is None:
        pfp = fp_div_safe(SCALE_FACTOR, n * SCALE_FACTOR)
        probs = [pfp] * n

    nf = 1 + D + D * (D + 1) // 2
    ph = phi_mean(pts)

    push_acc = [0] * nf
    for i in range(n):
        A, b = matrices[i], vectores[i]
        mapped = [
            [sum(fp_mul(A[r][c], pts[j][c]) for c in range(D)) + b[r] for r in range(D)]
            for j in range(len(pts))
        ]
        pm = phi_mean(mapped)
        for k in range(nf):
            push_acc[k] += fp_mul(probs[i], pm[k])

    return sum(fp_mul(ph[k] - push_acc[k], ph[k] - push_acc[k]) for k in range(nf))


# ── c2: Var(φ̂) ────────────────────────────────────────────────────────────────


def var_phi(pts):
    ph = phi_mean(pts)
    nf, N = len(ph), len(pts)
    acc = 0
    for p in pts:
        phx = phi(p)
        for k in range(nf):
            diff = phx[k] - ph[k]
            acc += fp_mul(diff, diff)
    return fp_div_safe(acc, N * SCALE_FACTOR)


# ── c5: huella de asimetría ────────────────────────────────────────────────────


def skew_finger(pts):
    N = len(pts)
    mu = [fp_div_safe(sum(p[k] for p in pts), N * SCALE_FACTOR) for k in range(D)]
    c = [[p[k] - mu[k] for k in range(D)] for p in pts]

    var_sum = sum(fp_mul(c[j][k], c[j][k]) for j in range(N) for k in range(D))
    var_total = fp_div_safe(var_sum, N * D * SCALE_FACTOR)
    sigma_fp = int((max(to_float(var_total), 1e-18) ** 0.5) * SCALE_FACTOR)
    s3 = fp_mul(fp_mul(sigma_fp, sigma_fp), sigma_fp)
    if s3 == 0:
        s3 = 1

    def m3(a, b, cc):
        acc = sum(fp_mul(fp_mul(c[j][a], c[j][b]), c[j][cc]) for j in range(N))
        return fp_div_safe(acc, N * SCALE_FACTOR)

    return [
        fp_div_safe(m3(0, 0, 0), s3),
        fp_div_safe(m3(0, 0, 1), s3),
        fp_div_safe(m3(0, 1, 1), s3),
        fp_div_safe(m3(1, 1, 1), s3),
    ]


# ── c6: dispersión de pares (grado 2) ─────────────────────────────────────────


def pair_dispersion(pts):
    N = len(pts)
    if N < 2:
        return 0
    total = 0
    for i in range(N):
        for j in range(i + 1, N):
            total += sum(
                fp_mul(pts[i][k] - pts[j][k], pts[i][k] - pts[j][k]) for k in range(D)
            )
    pairs = N * (N - 1) // 2
    return fp_div_safe(total, pairs * SCALE_FACTOR)


# ── c7: invariancia de la media ────────────────────────────────────────────────


def mu_invariance(pts, matrices, vectores):
    N, n = len(pts), len(matrices)
    pfp = fp_div_safe(SCALE_FACTOR, n * SCALE_FACTOR)
    mu = [fp_div_safe(sum(p[k] for p in pts), N * SCALE_FACTOR) for k in range(D)]
    push_mu = [0] * D
    for i in range(n):
        A, b = matrices[i], vectores[i]
        mm = [sum(fp_mul(A[r][c], mu[c]) for c in range(D)) + b[r] for r in range(D)]
        for k in range(D):
            push_mu[k] += fp_mul(pfp, mm[k])
    return sum(fp_mul(mu[k] - push_mu[k], mu[k] - push_mu[k]) for k in range(D))


# ── c8: ratio P₅/media de distancias ──────────────────────────────────────────


def min_mean_ratio(pts, n_sample=200):
    N = len(pts)
    dists = []
    step = max(1, N * (N - 1) // 2 // n_sample)
    idx = 0
    for i in range(N):
        for j in range(i + 1, N):
            if idx % step == 0:
                dists.append(
                    sum(
                        fp_mul(pts[i][k] - pts[j][k], pts[i][k] - pts[j][k])
                        for k in range(D)
                    )
                )
            idx += 1
    if not dists:
        return 0
    dists.sort()
    p5 = dists[max(0, len(dists) * 5 // 100)]
    mean_d = fp_div_safe(sum(dists), len(dists) * SCALE_FACTOR)
    return fp_div_safe(p5, mean_d) if mean_d else 0


# ── CriterionParams ────────────────────────────────────────────────────────────


class CriterionParams:
    """Parámetros calibrados (información pública, viajan en la transacción)."""

    def __init__(
        self,
        theta_IFS,
        sigma2_min,
        skew_ref,
        tau_skew,
        d2_min,
        thresh_c8,
        theta_mu,
        n_maps=4,
        probs=None,
    ):
        self.theta_IFS = theta_IFS
        self.sigma2_min = sigma2_min
        self.skew_ref = skew_ref
        self.tau_skew = tau_skew
        self.d2_min = d2_min
        self.thresh_c8 = thresh_c8
        self.theta_mu = theta_mu
        self.n_maps = n_maps
        self.probs = (
            probs or [fp_div_safe(SCALE_FACTOR, n_maps * SCALE_FACTOR)] * n_maps
        )

    def to_dict(self):
        return {
            k: getattr(self, k)
            for k in [
                "theta_IFS",
                "sigma2_min",
                "skew_ref",
                "tau_skew",
                "d2_min",
                "thresh_c8",
                "theta_mu",
                "n_maps",
                "probs",
            ]
        }

    @staticmethod
    def from_dict(d):
        return CriterionParams(**{k: d[k] for k in d})


def calibrate(
    attractor,
    matrices,
    vectores,
    N,
    n_samples=60,
    k_sigma=3.0,
    alpha_var=0.30,
    k_skew=5.0,
    d2_factor=0.25,
):
    """Calibra los umbrales desde el atractor real (ejecutar en keygen)."""
    import random

    n_att = len(attractor)

    AS_s = []
    Var_s = []
    skew_s = []
    ratio_s = []
    mu_s = []
    for _ in range(n_samples):
        sub = [attractor[i] for i in random.sample(range(n_att), min(N, n_att))]
        AS_s.append(to_float(delta_AS(sub, matrices, vectores)))
        Var_s.append(to_float(var_phi(sub)))
        skew_s.append([to_float(v) for v in skew_finger(sub)])
        ratio_s.append(to_float(min_mean_ratio(sub)))
        mu_s.append(to_float(mu_invariance(sub, matrices, vectores)))

    def fp(x):
        return int(x * SCALE_FACTOR)

    def m(lst):
        return sum(lst) / len(lst)

    def s(lst, mu):
        return (sum((x - mu) ** 2 for x in lst) / len(lst)) ** 0.5

    mAS = m(AS_s)
    sAS = s(AS_s, mAS)
    mVar = m(Var_s)
    mMu = m(mu_s)
    sMu = s(mu_s, mMu)
    mR = m(ratio_s)
    sR = s(ratio_s, mR)
    sk_ref = [m([ss[k] for ss in skew_s]) for k in range(4)]
    sk_errs = [
        (sum((ss[k] - sk_ref[k]) ** 2 for k in range(4))) ** 0.5 for ss in skew_s
    ]
    mSk = m(sk_errs)
    sSk = s(sk_errs, mSk)

    # distancia inter puntos fijos (bᵢ como vectores en FP)
    ids = [(i, j) for i in range(len(vectores)) for j in range(i + 1, len(vectores))]
    inter2 = [
        to_float(
            sum(
                fp_mul(vectores[i][k] - vectores[j][k], vectores[i][k] - vectores[j][k])
                for k in range(D)
            )
        )
        for i, j in ids
    ]
    inter_fp2 = min(inter2) / SCALE_FACTOR**2 if inter2 else 1.0

    return CriterionParams(
        theta_IFS=fp(mAS + k_sigma * sAS),
        sigma2_min=fp(mVar * alpha_var),
        skew_ref=[fp(v) for v in sk_ref],
        tau_skew=fp(mSk + k_skew * sSk),
        d2_min=fp(d2_factor * inter_fp2),
        thresh_c8=fp(max(0.02, mR - 4.0 * sR)),
        theta_mu=fp(mMu + k_sigma * sMu),
        n_maps=len(matrices),
    )


# ── CriterionResult + evaluate ─────────────────────────────────────────────────


class CriterionResult:
    def __init__(self, AS, Var, mu_err, sk_err, d2, r8, c1, c2, c3, c5, c6, c7, c8):
        self.AS = AS
        self.Var = Var
        self.mu_err = mu_err
        self.sk_err = sk_err
        self.d2 = d2
        self.r8 = r8
        self.c1 = c1
        self.c2 = c2
        self.c3 = c3
        self.c5 = c5
        self.c6 = c6
        self.c7 = c7
        self.c8 = c8
        self.pass_all = c1 and c2 and c3 and c5 and c6 and c7 and c8
        # Bit field encoding — criterion number maps to bit position:
        # bit 0: c1 | bit 1: c2 | bit 2: c3
        # bit 3: reserved=0 (c4 deprecated in v3, slot preserved)
        # bit 4: c5 | bit 5: c6 | bit 6: c7 | bit 7: c8
        self.packed = (
            int(c1)
            | (int(c2) << 1)
            | (int(c3) << 2)
            | (0       << 3)   # c4 deprecated — bit 3 always 0
            | (int(c5) << 4)
            | (int(c6) << 5)
            | (int(c7) << 6)
            | (int(c8) << 7)
        )

    def summary(self):
        p = [
            ("c1", self.c1),
            ("c2", self.c2),
            ("c3", self.c3),
            ("c5", self.c5),
            ("c6", self.c6),
            ("c7", self.c7),
            ("c8", self.c8),
        ]
        s = " ".join(f"{n}({'V' if f else 'X'})" for n, f in p)
        return f"{'PASA' if self.pass_all else 'FALLA'}  {s}"


def evaluate(x_final, matrices, vectores, params, N_total, n_act=None):
    """Evalúa el criterio compuesto sobre x_final."""
    if n_act is None:
        n_act = len(x_final)

    AS = delta_AS(x_final, matrices, vectores, params.probs)
    Var = var_phi(x_final)
    mu_err = mu_invariance(x_final, matrices, vectores)
    sk = skew_finger(x_final)
    sk_err = sum(
        fp_mul(sk[k] - params.skew_ref[k], sk[k] - params.skew_ref[k]) for k in range(4)
    )
    d2 = pair_dispersion(x_final)
    r8 = min_mean_ratio(x_final)

    HALF = SCALE_FACTOR // 2
    frac = fp_div_safe(n_act * SCALE_FACTOR, N_total * SCALE_FACTOR)

    return CriterionResult(
        AS=AS,
        Var=Var,
        mu_err=mu_err,
        sk_err=sk_err,
        d2=d2,
        r8=r8,
        c1=AS < params.theta_IFS,
        c2=Var > params.sigma2_min,
        c3=frac > HALF,
        c5=sk_err < params.tau_skew,
        c6=d2 > params.d2_min,
        c7=mu_err < params.theta_mu,
        c8=r8 > params.thresh_c8,
    )
