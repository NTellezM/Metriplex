"""Fix de consenso: operaciones de protocolo firmadas + votos de gobernanza."""
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch

from blockchain.chain import Blockchain
from blockchain.storage import Storage
from blockchain.block import Transaction
from blockchain.protocol_auth import (
    PROTOCOL_SIG_ACTIVATION, protocol_op_hash, governance_vote_hash,
    verify_vote_signature,
)

ACT = PROTOCOL_SIG_ACTIVATION


def make_bc():
    tmp = tempfile.mkdtemp()
    return Blockchain(Storage(f"{tmp}/t.db"))


def proto_tx(op, sender=None, amount=0, endpoint="1.2.3.4:65432"):
    sender = sender or [[[7]]]
    payload = {"op": op, "endpoint": endpoint}
    return Transaction(sender_m3=sender, receiver_m3=sender, amount=amount,
                       signature_data={"type": "X"}, payload=payload)


class ChainProtocolOpTests(unittest.TestCase):
    def setUp(self):
        self.bc = make_bc()

    def test_legacy_accepts_before_activation(self):
        # Antes de la activación, replay histórico: se acepta sin firma.
        tx = proto_tx("VALIDATOR_EXIT")
        with patch.object(self.bc, "_verify_signature") as vs:
            self.assertTrue(self.bc.validate_transaction(tx, block_index=ACT - 1))
            vs.assert_not_called()  # ni siquiera se intenta verificar (legacy)

    def test_strict_rejects_bad_signature(self):
        tx = proto_tx("VALIDATOR_EXIT")
        with patch.object(self.bc, "_verify_signature", return_value=False):
            self.assertFalse(self.bc.validate_transaction(tx, block_index=ACT))

    def test_strict_accepts_good_signature_over_canonical_hash(self):
        tx = proto_tx("VALIDATOR_EXIT")
        with patch.object(self.bc, "_verify_signature", return_value=True) as vs:
            self.assertTrue(self.bc.validate_transaction(tx, block_index=ACT))
        # se verificó sobre el hash canónico, no sobre otra cosa
        called_hash = vs.call_args.args[2]
        self.assertEqual(called_hash, protocol_op_hash(tx.sender_m3, tx.payload, tx.amount))

    def test_register_requires_real_stake(self):
        tx = proto_tx("VALIDATOR_REGISTER", amount=100 * 1073741824)
        with patch.object(self.bc, "_verify_signature", return_value=True), \
             patch.object(self.bc.state_db, "get_balance", return_value=0):
            self.assertFalse(self.bc.validate_transaction(tx, block_index=ACT))  # sin saldo real
        with patch.object(self.bc, "_verify_signature", return_value=True), \
             patch.object(self.bc.state_db, "get_balance", return_value=100 * 1073741824):
            self.assertTrue(self.bc.validate_transaction(tx, block_index=ACT))

    def test_forged_exit_from_public_hash_is_rejected(self):
        # Escenario de ataque: expulsar a un validador conocido sin su clave.
        victim_m3 = [[[42]]]
        tx = proto_tx("VALIDATOR_EXIT", sender=victim_m3)
        # firma real fallaría; simulamos que _verify_signature (ZK) la rechaza
        with patch.object(self.bc, "_verify_signature", return_value=False):
            self.assertFalse(self.bc.validate_transaction(tx, block_index=ACT))


class CanonicalHashConsistencyTests(unittest.TestCase):
    def test_emitter_and_verifier_agree(self):
        # El emisor (register_validator.py) firma este dict canónico;
        # el verificador computa protocol_op_hash. Deben coincidir.
        pub = [[[1]]]; STAKE = 100 * 1073741824; endpoint = "5.6.7.8:65436"
        canonical = {"op": "VALIDATOR_REGISTER", "sender_m3": pub,
                     "amount": STAKE, "endpoint": endpoint, "target_m3_hash": ""}
        emitter_hash = hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        payload = {"op": "VALIDATOR_REGISTER", "endpoint": endpoint,
                   "contraction_matrices": [1, 2]}  # extra fields ignorados
        verifier_hash = protocol_op_hash(pub, payload, STAKE)
        self.assertEqual(emitter_hash, verifier_hash)

    def test_op_hash_binds_op_and_fields(self):
        # Cambiar el op o el endpoint cambia el hash (no reutilizable).
        pub = [[[1]]]
        h1 = protocol_op_hash(pub, {"op": "VALIDATOR_EXIT", "endpoint": "a:1"}, 0)
        h2 = protocol_op_hash(pub, {"op": "VALIDATOR_REGISTER", "endpoint": "a:1"}, 0)
        h3 = protocol_op_hash(pub, {"op": "VALIDATOR_EXIT", "endpoint": "b:2"}, 0)
        self.assertNotEqual(h1, h2)
        self.assertNotEqual(h1, h3)


class GovernanceVoteTests(unittest.TestCase):
    def test_vote_hash_deterministic_and_target_bound(self):
        self.assertEqual(governance_vote_hash("abc"), governance_vote_hash("abc"))
        self.assertNotEqual(governance_vote_hash("abc"), governance_vote_hash("xyz"))

    def test_verify_vote_rejects_malformed(self):
        self.assertFalse(verify_vote_signature(None, [[[1]]], "h"))
        self.assertFalse(verify_vote_signature({}, [[[1]]], "h"))       # sin criterion_params
        self.assertFalse(verify_vote_signature({"criterion_params": {}}, [[[1]]], "h"))


if __name__ == "__main__":
    unittest.main()
