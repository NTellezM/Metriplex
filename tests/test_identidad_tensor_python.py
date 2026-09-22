"""Identidades cuyo public_m3 se creo con la ruta Python del tensor.

Caso real: nodo3 (203a4d51...) reproduce su public_m3 con error 0 en Python y
9,4e7 en Rust. Desde ZK_TOLERANCE_ACTIVATION su saldo quedo inmovilizado: la
regla estricta solo probaba Rust. Desde DUAL_TENSOR_ACTIVATION se prueba
tambien la ruta Python, con el mismo margen.
"""
import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from blockchain.rules import DUAL_TENSOR_ACTIVATION, ZK_TOLERANCE_ACTIVATION
from core.arithmetic import SCALE_FACTOR
from core.verifier import calibrate, evaluate
from crypto import tensors
from crypto.keys import derive_public_key_with_attractor, generate_private_key
from crypto.signatures import sign_transaction
from crypto.zkp import ZKEngine


def identidad_valida():
    while True:
        priv = generate_private_key()
        pub, att = derive_public_key_with_attractor(priv)
        params = calibrate(att, priv["A"], priv["b"], len(priv["A"]))
        if evaluate(att, priv["A"], priv["b"], params, len(att)).pass_all:
            return priv, pub, att, params


def firmar(priv, pub, att, params, receptor):
    carga = {"sender_m3": pub, "receiver_m3": receptor, "amount": 5 * SCALE_FACTOR,
             "fee": 0, "payload": None}
    sig = sign_transaction(priv, carga, pub, criterion_params=params, attractor=att)
    tx_hash = hashlib.sha256(
        json.dumps(carga, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return sig, tx_hash, params


def error_max(a, b):
    return max(abs(a[i][j][k] - b[i][j][k]) for i in range(4) for j in range(4) for k in range(4))


class IdentidadTensorPythonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.priv, cls.pub_rust, cls.att, cls.params = identidad_valida()
        # La misma clave privada, pero con el public_m3 que habria dado la
        # ruta Python: exactamente la situacion de nodo3.
        cls.pub_py = tensors.calculate_m3_tensor_python(cls.att)
        cls.otro = identidad_valida()

    def verificar(self, pub, altura, priv=None, att=None, params=None):
        sig, tx_hash, params = firmar(priv or self.priv, pub, att or self.att,
                                      params or self.params, self.otro[1])
        return ZKEngine.verify_proof(proof=sig, public_m3=pub, tx_hash=tx_hash,
                                     criterion_params=params, N_total=2000,
                                     block_index=altura)

    def test_premisa_las_dos_rutas_difieren(self):
        # Sin esto el test no reproduce el caso de nodo3.
        self.assertTrue(tensors.USING_RUST, "estos tests necesitan la extension Rust")
        magnitud = max(abs(v) for a in self.pub_py for b in a for v in b)
        self.assertGreater(error_max(self.pub_rust, self.pub_py), 0.01 * magnitud)

    def test_identidad_python_bloqueada_antes_de_la_activacion(self):
        self.assertFalse(self.verificar(self.pub_py, DUAL_TENSOR_ACTIVATION - 1))

    def test_identidad_python_aceptada_desde_la_activacion(self):
        self.assertTrue(self.verificar(self.pub_py, DUAL_TENSOR_ACTIVATION))

    def test_identidad_rust_sigue_aceptada(self):
        for altura in (ZK_TOLERANCE_ACTIVATION, DUAL_TENSOR_ACTIVATION):
            self.assertTrue(self.verificar(self.pub_rust, altura))

    def test_no_se_puede_firmar_por_una_identidad_python_ajena(self):
        # Atacante con su propio atractor intentando gastar desde pub_py.
        priv, _, att, params = self.otro
        self.assertFalse(self.verificar(self.pub_py, DUAL_TENSOR_ACTIVATION,
                                        priv=priv, att=att, params=params))

    def test_ni_por_una_identidad_rust_ajena(self):
        priv, _, att, params = self.otro
        self.assertFalse(self.verificar(self.pub_rust, DUAL_TENSOR_ACTIVATION,
                                        priv=priv, att=att, params=params))

    def test_la_ruta_python_no_se_calcula_si_rust_coincide(self):
        with patch.object(tensors, "calculate_m3_tensor_python",
                          side_effect=AssertionError("ruta lenta innecesaria")):
            self.assertTrue(self.verificar(self.pub_rust, DUAL_TENSOR_ACTIVATION))

    def test_identidad_real_de_nodo3(self):
        # Datos publicos de la cadena: coinbase de nodo3 en el bloque 122424.
        # Con N_PROOF=2000 x_final ES su atractor. Fija la aritmetica de la
        # ruta Python: si alguien la "optimiza" y cambia un redondeo, falla.
        with open(Path(__file__).with_name("nodo3_publico.json")) as f:
            real = json.load(f)
        self.assertEqual(tensors.calculate_m3_tensor_python(real["x_final"]), real["public_m3"])
        self.assertNotEqual(tensors.calculate_m3_tensor(real["x_final"]), real["public_m3"])

if __name__ == "__main__":
    unittest.main()
