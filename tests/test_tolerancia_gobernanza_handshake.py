"""Endurecer el anti-forge en votos de gobernanza y en el handshake P2P.

Antes, verify_proof sin block_index caia en la tolerancia absoluta antigua
(~22x la magnitud del tensor): el chequeo empirico no distinguia una clave de
otra. Un atacante podia firmar un voto de gobernanza —o un handshake— en nombre
de cualquier validador usando su PROPIO atractor, porque el pi se liga al
m3_hash publico de la victima y el unico control que ata x_final a la clave
real es el tensor empirico.

Los votos se endurecen por altura (GOVERNANCE_STRICT_ACTIVATION); el handshake,
que no es consenso ni tiene altura, con strict_latest=True.
"""
import hashlib
import json
import unittest

from blockchain.protocol_auth import governance_vote_hash, verify_vote_signature
from blockchain.rules import GOVERNANCE_STRICT_ACTIVATION
from core.verifier import calibrate, evaluate
from crypto import tensors
from crypto.keys import derive_public_key_with_attractor, generate_private_key
from crypto.zkp import ZKEngine


def identidad():
    while True:
        priv = generate_private_key()
        pub, att = derive_public_key_with_attractor(priv)
        p = calibrate(att, priv["A"], priv["b"], len(priv["A"]))
        if evaluate(att, priv["A"], priv["b"], p, len(att)).pass_all:
            return {"priv": priv, "pub": pub, "att": att, "params": p}


def prueba_para(quien, mensaje, declarando_pub=None):
    """Prueba ZK firmada con el atractor de `quien`, declarando `declarando_pub`
    como clave publica (por defecto la suya). Con otra clave = falsificacion."""
    pub = declarando_pub if declarando_pub is not None else quien["pub"]
    proof = ZKEngine.generate_proof(
        private_key=quien["priv"], public_m3=pub, tx_hash=mensaje,
        criterion_params=quien["params"], N_total=2000, attractor=quien["att"],
    )
    proof["criterion_params"] = vars(quien["params"])
    return proof


class ToleranciaGobernanzaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.A = identidad()                 # victima / votante legitimo
        cls.B = identidad()                 # atacante
        cls.vh = governance_vote_hash("objetivo1234")
        cls.legit = prueba_para(cls.A, cls.vh)
        # B firma con SU atractor pero declara la clave de A:
        cls.forjada = prueba_para(cls.B, cls.vh, declarando_pub=cls.A["pub"])

    # ── votos ────────────────────────────────────────────────────────────────
    def test_voto_legitimo_se_acepta_tras_la_activacion(self):
        self.assertTrue(verify_vote_signature(
            self.legit, self.A["pub"], self.vh, GOVERNANCE_STRICT_ACTIVATION))

    def test_voto_forjado_se_rechaza_tras_la_activacion(self):
        self.assertFalse(verify_vote_signature(
            self.forjada, self.A["pub"], self.vh, GOVERNANCE_STRICT_ACTIVATION))

    def test_antes_de_la_activacion_se_mantiene_la_regla_antigua(self):
        # Premisa del arreglo: con la tolerancia antigua el voto forjado colaba.
        # Por debajo de la altura, state.py pasa block_index=None (comprobado en
        # test_state_pasa_none_por_debajo_de_la_altura), preservando esa regla
        # para no romper consenso durante el despliegue.
        self.assertTrue(verify_vote_signature(
            self.forjada, self.A["pub"], self.vh, None))

    def test_state_pasa_none_por_debajo_de_la_altura(self):
        # La compuerta de altura vive en state.py: por debajo pasa None (regla
        # antigua), en/por encima pasa el block_index real (regla estricta).
        import inspect
        from blockchain import state
        fuente = inspect.getsource(state.StateDB.apply_transaction)
        self.assertIn("GOVERNANCE_STRICT_ACTIVATION", fuente)
        self.assertIn(
            "block_index if block_index >= GOVERNANCE_STRICT_ACTIVATION else None", fuente)

    def test_identidad_python_vota_via_regla_dual(self):
        # Una clave estilo nodo3 (tensor Python) debe poder votar tras la
        # activacion, que ya es >= DUAL_TENSOR_ACTIVATION.
        pub_py = tensors.calculate_m3_tensor_python(self.A["att"])
        proof = prueba_para(self.A, self.vh, declarando_pub=pub_py)
        self.assertTrue(verify_vote_signature(
            proof, pub_py, self.vh, GOVERNANCE_STRICT_ACTIVATION))

    # ── handshake ──────────────────────────────────────────────────────────────
    def test_handshake_estricto_acepta_legitimo_y_rechaza_forjado(self):
        self.assertTrue(ZKEngine.verify_proof(
            self.legit, self.A["pub"], self.vh, self.A["params"], strict_latest=True))
        self.assertFalse(ZKEngine.verify_proof(
            self.forjada, self.A["pub"], self.vh, self.A["params"], strict_latest=True))

    def test_handshake_estricto_acepta_identidad_python(self):
        pub_py = tensors.calculate_m3_tensor_python(self.A["att"])
        proof = prueba_para(self.A, self.vh, declarando_pub=pub_py)
        self.assertTrue(ZKEngine.verify_proof(
            proof, pub_py, self.vh, self.A["params"], strict_latest=True))

    def test_sin_strict_latest_la_forjada_colaria(self):
        # Demuestra que strict_latest es lo que cierra el agujero: sin el, y sin
        # block_index, la prueba forjada pasa (tolerancia absoluta antigua).
        self.assertTrue(ZKEngine.verify_proof(
            self.forjada, self.A["pub"], self.vh, self.A["params"]))


if __name__ == "__main__":
    unittest.main()
