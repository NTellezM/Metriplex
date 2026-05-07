"""
Módulo de aritmética determinista para el protocolo CAF.
Garantiza que todos los nodos produzcan resultados idénticos,
independientemente de su arquitectura de hardware.
"""

# Factor de escala para punto fijo (S = 2^30)
# Permite representar valores fraccionarios usando enteros.
SCALE_FACTOR = 2**30

# Primo de Goldilocks para operaciones en campo finito
# P = 2^64 - 2^32 + 1
GOLDILOCKS_PRIME = 18446744069414584321

def to_fixed_point(value: float) -> int:
    """
    Convierte un valor de punto flotante a la representación interna de punto fijo.
    Se debe utilizar exclusivamente en la ingesta de parámetros, no durante la simulación.
    """
    return int(value * SCALE_FACTOR)

def to_float(value: int) -> float:
    """
    Convierte un valor de punto fijo de vuelta a flotante.
    Uso exclusivo para visualización en clientes e interfaces, nunca en lógica de consenso.
    """
    return value / SCALE_FACTOR

def fp_mul(a: int, b: int) -> int:
    """
    Multiplicación en punto fijo con truncamiento determinista.
    Conserva la escala dividiendo el producto por el factor de escala.
    """
    return (a * b) // SCALE_FACTOR

def mod_add(a: int, b: int) -> int:
    """
    Suma modular estricta dentro del campo de Goldilocks.
    """
    return (a + b) % GOLDILOCKS_PRIME

def mod_mul(a: int, b: int) -> int:
    """
    Multiplicación modular estricta dentro del campo de Goldilocks.
    """
    return (a * b) % GOLDILOCKS_PRIME

def fp_div_safe(a: int, b: int) -> int:
    """
    División en punto fijo con protección contra división por cero.
    Multiplica el numerador por la escala antes de dividir para mantener la precisión.
    """
    if b == 0:
        raise ValueError("División por cero detectada en aritmética de punto fijo.")
    return (a * SCALE_FACTOR) // b