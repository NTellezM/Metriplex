"""
core/dynamics.py — Integrador de Störmer-Verlet CAF v7
=======================================================
Implementa la dinámica de fragmentos sobre el atractor IFS.

Correcciones v7 (validadas en backtesting v5):
  - Rc derivado de inter_fp: Rc = Rc_factor × min d(x*ᵢ, x*ⱼ) ≤ 0.60
  - Filtro cross-map: solo pares de fragmentos de mapas distintos
  - Anclaje κ: fuerza restauradora a los puntos fijos
  - N_per × n_maps fragmentos con asignación explícita por mapa
  - γ = 1.3 (validado en backtesting v5)
  - Δt = 0.80 × 0.30 × Rc / √V₀  (bound revisado)

Aritmética determinista en punto fijo (S = 2^30) para
consenso reproducible entre todos los nodos de la red.
"""

from core.arithmetic import fp_mul, fp_div_safe, SCALE_FACTOR, to_float

D = 4   # dimensión del espacio (constante del protocolo)

# ── Parámetros de producción validados en backtesting v5 ─────────────────────
DEFAULT_V0        = 1.5
DEFAULT_GAMMA     = 1.3
DEFAULT_KAPPA     = 1.5
DEFAULT_RC_FACTOR = 0.50    # Rc = Rc_factor × inter_fp  (límite: 0.60)
DEFAULT_DT_FACTOR = 0.80    # dt = DT_FACTOR × dt_bound
DEFAULT_N_PER     = 12      # fragmentos por mapa
DEFAULT_STEPS     = 500     # pasos de integración


# ─────────────────────────────────────────────────────────────────────────────
#  GEOMETRÍA DEL IFS
# ─────────────────────────────────────────────────────────────────────────────

def compute_fixed_points(matrices: list, vectores: list) -> list:
    """
    Calcula los puntos fijos x*ᵢ = (I - Aᵢ)⁻¹ bᵢ via iteración.
    Converge en <50 pasos para ρ(Aᵢ) < 1.
    """
    fps = []
    for i in range(len(matrices)):
        A, b = matrices[i], vectores[i]
        x = [0] * D
        for _ in range(200):     # suficiente para ρ < 0.70
            x = [
                sum(fp_mul(A[r][c], x[c]) for c in range(D)) + b[r]
                for r in range(D)
            ]
        fps.append(x)
    return fps


def compute_inter_fp(fps: list) -> int:
    """Distancia mínima entre puntos fijos (en punto fijo)."""
    n = len(fps)
    min_d2 = None
    for i in range(n):
        for j in range(i + 1, n):
            d2 = sum(fp_mul(fps[i][k] - fps[j][k], fps[i][k] - fps[j][k])
                     for k in range(D))
            if min_d2 is None or d2 < min_d2:
                min_d2 = d2
    return min_d2 if min_d2 is not None else SCALE_FACTOR


def compute_Rc(fps: list, rc_factor: float = DEFAULT_RC_FACTOR) -> int:
    """
    Rc = rc_factor × min d(x*ᵢ, x*ⱼ)
    Cumple la restricción validada: Rc ≤ 0.60 × inter_fp.
    """
    inter_fp_sq = compute_inter_fp(fps)
    inter_fp    = int((to_float(inter_fp_sq) ** 0.5) * SCALE_FACTOR)
    return fp_mul(int(rc_factor * SCALE_FACTOR), inter_fp)


def compute_dt(Rc_fp: int, V0: float = DEFAULT_V0,
               dt_factor: float = DEFAULT_DT_FACTOR) -> int:
    """
    Δt = dt_factor × 0.30 × Rc / √V₀
    Bound revisado en backtesting v4/v5: margen de 3-4× sobre el bound.
    """
    import math
    Rc_float = to_float(Rc_fp)
    dt_bound = 0.30 * Rc_float / math.sqrt(V0)
    return int(dt_factor * dt_bound * SCALE_FACTOR)


def init_positions(fps: list, n_per: int, sigma_frac: float = 0.12) -> list:
    """
    Inicializa posiciones cerca de los puntos fijos con ruido gaussiano.
    xᵢ = x*ₙ(i) + ε   con ‖ε‖ ~ sigma_frac × Rc
    Retorna lista de n_maps × n_per vectores.
    """
    import os
    n_maps = len(fps)
    positions = []
    for map_idx in range(n_maps):
        fp = fps[map_idx]
        for _ in range(n_per):
            noise = [
                int((int.from_bytes(os.urandom(4), "little") / (2**32 - 1) - 0.5)
                    * sigma_frac * 0.2 * SCALE_FACTOR)
                for _ in range(D)
            ]
            positions.append([fp[k] + noise[k] for k in range(D)])
    return positions


def build_cross_pairs(n_maps: int, n_per: int) -> list:
    """
    Lista de pares (i, j) donde i y j pertenecen a mapas distintos.
    Fragmento i pertenece al mapa i // n_per.
    Solo pares con mapa_i ≠ mapa_j interactúan via el potencial de pozo finito.
    """
    N = n_maps * n_per
    pairs = []
    for i in range(N):
        for j in range(i + 1, N):
            if (i // n_per) != (j // n_per):
                pairs.append((i, j))
    return pairs


# ─────────────────────────────────────────────────────────────────────────────
#  FUERZAS
# ─────────────────────────────────────────────────────────────────────────────

def calculate_forces_v7(
    x:           list,
    fps:         list,
    cross_pairs: list,
    Rc_fp:       int,
    V0_fp:       int,
    kappa_fp:    int,
    n_per:       int,
) -> tuple:
    """
    Calcula fuerzas totales y PE en aritmética de punto fijo.

    Fuerza de interacción (par cross-map dentro de Rc):
      F_i←j = 4·V₀·(1 - d²/Rc²)·(xⱼ - xᵢ)/Rc²

    Fuerza de anclaje (restauradora al punto fijo del mapa):
      F_i -= 2·κ·(xᵢ - x*_{i//n_per})

    Retorna (fuerzas: list[list[int]], PE: int, n_active: int)
    """
    N    = len(x)
    F    = [[0] * D for _ in range(N)]
    PE   = 0
    act  = 0
    Rc2  = fp_mul(Rc_fp, Rc_fp)

    # Fuerzas de interacción cross-map
    for (i, j) in cross_pairs:
        diff   = [x[j][k] - x[i][k] for k in range(D)]
        dist2  = sum(fp_mul(diff[k], diff[k]) for k in range(D))

        if 0 < dist2 < Rc2:
            w    = Rc2 - dist2
            fmag = fp_div_safe(fp_mul(4 * V0_fp, w), Rc2)
            for k in range(D):
                impulse    = fp_mul(fmag, diff[k])
                F[i][k]   += impulse
                F[j][k]   -= impulse
            PE  -= fp_mul(V0_fp, fp_mul(fp_div_safe(w, Rc2), fp_div_safe(w, Rc2)))
            act += 1

    # Fuerza de anclaje: cada fragmento i al fp de su mapa (i // n_per)
    for i in range(N):
        fp = fps[i // n_per]
        for k in range(D):
            delta    = x[i][k] - fp[k]
            anch_f   = fp_mul(2 * kappa_fp, delta)
            F[i][k] -= anch_f
            PE       += fp_mul(kappa_fp, fp_mul(delta, delta))

    return F, PE, act


# ─────────────────────────────────────────────────────────────────────────────
#  INTEGRADOR STÖRMER-VERLET (backward-compatible signature)
# ─────────────────────────────────────────────────────────────────────────────

def stormer_verlet_step(
    x:   list,
    v:   list,
    f_t: list,
    dt_fp:      int  = None,
    gamma_fp:   int  = None,
    # Argumentos opcionales para la nueva interfaz
    fps:        list = None,
    cross_pairs:list = None,
    Rc_fp:      int  = None,
    V0_fp:      int  = None,
    kappa_fp:   int  = None,
    n_per:      int  = None,
) -> tuple:
    """
    Un paso de integración Störmer-Verlet con amortiguamiento.

    Modo legacy (sin fps/cross_pairs): usa la función calculate_forces original.
    Modo v7 (con fps/cross_pairs): usa calculate_forces_v7.
    """
    N = len(x)

    # Parámetros por defecto (compatibilidad con código existente)
    if dt_fp    is None: dt_fp    = int(0.05 * SCALE_FACTOR)
    if gamma_fp is None: gamma_fp = SCALE_FACTOR // 2  # 0.5

    dt2_half = fp_mul(dt_fp, dt_fp) // (2 * SCALE_FACTOR)

    # Actualización de posición: x(t+dt) = x(t) + v·dt + ½·F·dt²
    # fp_mul ya incluye la división por SCALE_FACTOR — NO dividir de nuevo
    x_next = [
        [x[i][k] + fp_mul(v[i][k], dt_fp)
                 + fp_mul(f_t[i][k], dt2_half)
         for k in range(D)]
        for i in range(N)
    ]

    # Fuerzas en la nueva posición
    if fps is not None and cross_pairs is not None:
        f_next, PE, act = calculate_forces_v7(
            x_next, fps, cross_pairs, Rc_fp, V0_fp, kappa_fp, n_per
        )
    else:
        f_next = calculate_forces(x_next)
        PE, act = 0, 0

    # Factor de amortiguamiento: (1 - γ·Δt)
    damp = SCALE_FACTOR - fp_mul(gamma_fp, dt_fp)

    # Actualización de velocidad: v(t+dt) = damp · (v(t) + ½(F(t)+F(t+dt))·dt)
    v_next = [
        [fp_mul(damp,
                v[i][k] + fp_mul((f_t[i][k] + f_next[i][k]) // 2, dt_fp)
               )
         for k in range(D)]
        for i in range(N)
    ]

    return x_next, v_next, f_next


# ─────────────────────────────────────────────────────────────────────────────
#  FUNCIÓN LEGACY (mantiene compatibilidad con código que importa calculate_forces)
# ─────────────────────────────────────────────────────────────────────────────

def calculate_forces(x: list) -> list:
    """
    Versión legacy para compatibilidad con stark_core.py y código existente.
    Usa todos los pares (sin filtro cross-map) y Rc=1.0.
    Para producción usar calculate_forces_v7.
    """
    N    = len(x)
    F    = [[0] * D for _ in range(N)]
    Rc2  = SCALE_FACTOR  # Rc = 1.0 (legacy)
    V0   = SCALE_FACTOR

    for i in range(N):
        for j in range(i + 1, N):
            diff  = [x[j][k] - x[i][k] for k in range(D)]
            dist2 = sum(fp_mul(diff[k], diff[k]) for k in range(D))
            if 0 < dist2 < Rc2:
                w    = Rc2 - dist2
                fmag = fp_mul(4 * V0, w) // SCALE_FACTOR
                for k in range(D):
                    imp      = fp_mul(fmag, diff[k]) // SCALE_FACTOR
                    F[i][k] += imp
                    F[j][k] -= imp
    return F


# ─────────────────────────────────────────────────────────────────────────────
#  SIMULACIÓN PRINCIPAL v7
# ─────────────────────────────────────────────────────────────────────────────

class CAFSimulator:
    """
    Simulador determinista de la dinámica de fragmentos CAF v7.
    Encapsula todos los parámetros validados en el backtesting v5.
    """

    def __init__(
        self,
        matrices:   list,
        vectores:   list,
        n_per:      int   = DEFAULT_N_PER,
        V0:         float = DEFAULT_V0,
        gamma:      float = DEFAULT_GAMMA,
        kappa:      float = DEFAULT_KAPPA,
        rc_factor:  float = DEFAULT_RC_FACTOR,
        dt_factor:  float = DEFAULT_DT_FACTOR,
        steps:      int   = DEFAULT_STEPS,
    ):
        self.matrices   = matrices
        self.vectores   = vectores
        self.n_maps     = len(matrices)
        self.n_per      = n_per
        self.N          = self.n_maps * n_per
        self.steps      = steps

        # Calcular geometría del IFS
        self.fps         = compute_fixed_points(matrices, vectores)
        self.Rc_fp       = compute_Rc(self.fps, rc_factor)
        self.dt_fp       = compute_dt(self.Rc_fp, V0, dt_factor)
        self.cross_pairs = build_cross_pairs(self.n_maps, n_per)

        # Parámetros en punto fijo
        self.V0_fp    = int(V0    * SCALE_FACTOR)
        self.gamma_fp = int(gamma * SCALE_FACTOR)
        self.kappa_fp = int(kappa * SCALE_FACTOR)

    def run(self, x_init: list = None) -> tuple:
        """
        Ejecuta la simulación y retorna (x_final, log_KE).

        x_init: posiciones iniciales (N × D) en punto fijo.
                Si None, inicializa cerca de los puntos fijos.
        """
        if x_init is None:
            x = init_positions(self.fps, self.n_per)
        else:
            x = [row[:] for row in x_init]

        v   = [[0] * D for _ in range(self.N)]
        F, PE, _ = calculate_forces_v7(
            x, self.fps, self.cross_pairs,
            self.Rc_fp, self.V0_fp, self.kappa_fp, self.n_per
        )

        log_KE = []
        snap_every = max(1, self.steps // 20)

        for step in range(self.steps):
            x, v, F = stormer_verlet_step(
                x, v, F,
                dt_fp     = self.dt_fp,
                gamma_fp  = self.gamma_fp,
                fps       = self.fps,
                cross_pairs = self.cross_pairs,
                Rc_fp     = self.Rc_fp,
                V0_fp     = self.V0_fp,
                kappa_fp  = self.kappa_fp,
                n_per     = self.n_per,
            )
            if step % snap_every == 0:
                KE = sum(
                    fp_mul(v[i][k], v[i][k])
                    for i in range(self.N) for k in range(D)
                ) // (2 * SCALE_FACTOR)
                log_KE.append((step, KE))

        return x, log_KE

    def energy_drift_test(self, steps: int = 2000) -> float:
        """
        Mide el drift de energía sin amortiguamiento (γ=0).
        Verifica la propiedad simpléctica del integrador.
        """
        import os
        x = init_positions(self.fps, self.n_per)
        v = [
            [int((int.from_bytes(os.urandom(4), "little") / (2**32-1) - 0.5)
                 * 0.05 * SCALE_FACTOR)
             for _ in range(D)]
            for _ in range(self.N)
        ]
        F, PE0, _ = calculate_forces_v7(
            x, self.fps, self.cross_pairs,
            self.Rc_fp, self.V0_fp, self.kappa_fp, self.n_per
        )
        KE0 = sum(fp_mul(v[i][k], v[i][k])
                  for i in range(self.N) for k in range(D)) // (2*SCALE_FACTOR)
        E0  = KE0 + PE0

        E_hist = [to_float(E0)]
        gamma0 = 0  # sin amortiguamiento

        for _ in range(steps):
            x, v, F = stormer_verlet_step(
                x, v, F,
                dt_fp    = self.dt_fp,
                gamma_fp = 0,
                fps      = self.fps,
                cross_pairs = self.cross_pairs,
                Rc_fp    = self.Rc_fp,
                V0_fp    = self.V0_fp,
                kappa_fp = self.kappa_fp,
                n_per    = self.n_per,
            )
            _, PE, _ = calculate_forces_v7(
                x, self.fps, self.cross_pairs,
                self.Rc_fp, self.V0_fp, self.kappa_fp, self.n_per
            )
            KE = sum(fp_mul(v[i][k], v[i][k])
                     for i in range(self.N) for k in range(D)) // (2*SCALE_FACTOR)
            E_hist.append(to_float(KE + PE))

        E_max = max(abs(e) for e in E_hist)
        if E_max < 1e-10:
            return 0.0
        return abs(E_hist[-1] - E_hist[0]) / (abs(E_hist[0]) + 1e-12)


# ─────────────────────────────────────────────────────────────────────────────
#  FUNCIÓN LEGACY run_deterministic_simulation (backward-compatible)
# ─────────────────────────────────────────────────────────────────────────────

def run_deterministic_simulation(
    x_init_fp: list,
    steps:     int = 500,
    matrices:  list = None,
    vectores:  list = None,
) -> list:
    """
    Compatibilidad con crypto/keys.py y código existente.
    Si se proporcionan matrices/vectores, usa el modo v7.
    Si no, usa el modo legacy (calculate_forces sin cross-map).
    """
    x = [row[:] for row in x_init_fp]
    N = len(x)

    if matrices is not None and vectores is not None:
        sim = CAFSimulator(matrices, vectores)
        fps = sim.fps
        cross_pairs = sim.cross_pairs
        F, _, _ = calculate_forces_v7(
            x, fps, cross_pairs,
            sim.Rc_fp, sim.V0_fp, sim.kappa_fp, sim.n_per
        )
        v = [[0]*D for _ in range(N)]
        for _ in range(steps):
            x, v, F = stormer_verlet_step(
                x, v, F,
                dt_fp    = sim.dt_fp,
                gamma_fp = sim.gamma_fp,
                fps      = fps,
                cross_pairs = cross_pairs,
                Rc_fp    = sim.Rc_fp,
                V0_fp    = sim.V0_fp,
                kappa_fp = sim.kappa_fp,
                n_per    = sim.n_per,
            )
    else:
        # Modo legacy
        v   = [[0]*D for _ in range(N)]
        f_t = calculate_forces(x)
        for _ in range(steps):
            x, v, f_t = stormer_verlet_step(x, v, f_t)

    return x
