import sys, json
sys.path.insert(0, ".")
import numpy as np
from core.arithmetic import SCALE_FACTOR
from core.verifier import calibrate, evaluate
from crypto.keystore import save_keystore

def chaos_numpy(matrices, vectores, iterations=2000, burn_in=300):
    K = len(matrices)
    D = len(matrices[0])
    M = np.array(matrices, dtype=np.float64) / SCALE_FACTOR
    V = np.array(vectores, dtype=np.float64) / SCALE_FACTOR
    idx = np.random.randint(0, K, size=iterations+burn_in)
    x = np.zeros(D)
    att = np.empty((iterations, D))
    for i in range(iterations+burn_in):
        x = np.dot(M[idx[i]], x) + V[idx[i]]
        if i >= burn_in:
            att[i-burn_in] = x
    return (att * SCALE_FACTOR).astype(np.int64).tolist()

with open("wallet_nt_laptop.json") as f:
    w = json.load(f)
priv = w["private_key"]
pub = w["public_m3"]
print("Calibrando...")
for i in range(10):
    att = chaos_numpy(priv["A"], priv["b"])
    N = len(att)
    params = calibrate(att, priv["A"], priv["b"], N)
    result = evaluate(att, priv["A"], priv["b"], params, N)
    if result.pass_all:
        print(f"Intento {i+1}: PASA")
        save_keystore("123", priv, pub, params.__dict__, att, "keystore_nt_laptop.json")
        print("Listo")
        break
    else:
        print(f"Intento {i+1}: {result.summary()}")
