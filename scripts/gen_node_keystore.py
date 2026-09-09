#!/usr/bin/env python3
"""Genera un keystore de nodo con material privado aleatorio (256 bits de
entropía del sistema) y lo guarda cifrado. Imprime la identidad M3.

Uso: gen_node_keystore.py <ruta_salida> <password>
"""
import os
import sys
import json
import hashlib
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crypto.keys import (
    chaos_game, _make_contraction_seeded, validate_r1, validate_scale,
    validate_kruskal, N, D, RHO_MIN, RHO_MAX, MAX_KEYGEN_ATTEMPTS,
)
from crypto.tensors import calculate_m3_tensor
from core.verifier import calibrate, evaluate
from crypto.keystore import save_keystore


def generar():
    # Semilla de 256 bits del sistema (no derivada de ningún dato público).
    rng = np.random.RandomState(np.frombuffer(os.urandom(32), dtype=np.uint32))
    for _ in range(MAX_KEYGEN_ATTEMPTS):
        A, b = [], []
        for _ in range(N):
            sc = float(rng.uniform(RHO_MIN, RHO_MAX))
            A.append(_make_contraction_seeded(sc, rng))
            b.append([int(rng.uniform(-2**30, 2**30)) for _ in range(D)])
        if not (validate_r1(A)[0] and validate_scale(A)[0] and validate_kruskal(b, N)[0]):
            continue
        try:
            att = chaos_game(A, b)
            params = calibrate(att, A, b, len(att))
            if not evaluate(att, A, b, params, len(att)).pass_all:
                continue
            return {"A": A, "b": b}, calculate_m3_tensor(att), params, att
        except Exception:
            continue
    raise RuntimeError("no se pudo generar un keystore válido")


def main():
    if len(sys.argv) != 3:
        print("uso: gen_node_keystore.py <ruta_salida> <password>", file=sys.stderr)
        sys.exit(2)
    out_path, password = sys.argv[1], sys.argv[2]

    priv, m3, params, att = generar()
    params_dict = params.to_dict() if hasattr(params, "to_dict") else params
    save_keystore(password, priv, m3, params_dict, att, out_path)
    os.chmod(out_path, 0o600)

    m3_hash = hashlib.sha256(
        json.dumps(m3, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    # línea parseable por join.sh
    print(f"IDENTITY={m3_hash}")


if __name__ == "__main__":
    main()
