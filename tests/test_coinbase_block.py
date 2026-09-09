"""Validación de coinbase a nivel de bloque: unicidad + monto según la fórmula."""
import tempfile
import unittest
from unittest.mock import patch

from blockchain.chain import Blockchain
from blockchain.storage import Storage
from blockchain.block import Block, Transaction
from blockchain import emission
from blockchain.emission import expected_coinbase_reward, m3_hash


def make_bc_with_validator():
    bc = Blockchain(Storage(f"{tempfile.mkdtemp()}/t.db"))
    leader_m3 = [[[5, 5, 5, 5]]]
    lh = m3_hash(leader_m3)
    bc.state_db.validator_registry.validators[lh] = {
        "m3": leader_m3, "m3_hash": lh, "endpoint": "x:1", "stake": 100 * 1073741824,
        "registered_at": 0, "slashed": False, "lambda_value": -0.6,
        "contraction_matrices": None,
    }
    return bc, leader_m3, lh


def build_block(bc, txs, index=1):
    prev = bc.chain[-1]
    b = Block(index=index, transactions=txs, previous_hash=prev.hash, timestamp=1234.0)
    b.hash = b.calculate_hash()
    return b


def coinbase(receiver, amount):
    return Transaction(sender_m3=[], receiver_m3=receiver, amount=amount,
                       signature_data={"type": "COINBASE"})


class CoinbaseBlockTests(unittest.TestCase):
    def setUp(self):
        self.bc, self.leader, self.lh = make_bc_with_validator()
        self.reward = expected_coinbase_reward(self.bc.state_db.validator_registry, 1, self.lh)
        self.assertGreater(self.reward, 0)

    def test_correct_coinbase_accepted(self):
        with patch.object(emission, "COINBASE_ACTIVATION", 1):
            b = build_block(self.bc, [coinbase(self.leader, self.reward)])
            self.assertTrue(self.bc.add_block(b, skip_zk=True))

    def test_inflated_amount_rejected(self):
        with patch.object(emission, "COINBASE_ACTIVATION", 1):
            b = build_block(self.bc, [coinbase(self.leader, self.reward + 1_000_000 * 1073741824)])
            self.assertFalse(self.bc.add_block(b, skip_zk=True))

    def test_two_coinbases_rejected(self):
        with patch.object(emission, "COINBASE_ACTIVATION", 1):
            b = build_block(self.bc, [coinbase(self.leader, self.reward),
                                      coinbase(self.leader, self.reward)])
            self.assertFalse(self.bc.add_block(b, skip_zk=True))

    def test_receiver_not_validator_rejected(self):
        with patch.object(emission, "COINBASE_ACTIVATION", 1):
            stranger = [[[9, 9, 9, 9]]]
            r = expected_coinbase_reward(self.bc.state_db.validator_registry, 1, m3_hash(stranger))
            b = build_block(self.bc, [coinbase(stranger, r)])
            self.assertFalse(self.bc.add_block(b, skip_zk=True))

    def test_coinbase_not_position_zero_rejected(self):
        with patch.object(emission, "COINBASE_ACTIVATION", 1):
            normal = Transaction(sender_m3=[[[1]]], receiver_m3=self.leader, amount=1,
                                 signature_data={"type": "X"})
            b = build_block(self.bc, [normal, coinbase(self.leader, self.reward)])
            self.assertFalse(self.bc.add_block(b, skip_zk=True))

    def test_legacy_before_activation_accepts_any_amount(self):
        # Antes de la activación, cualquier coinbase pasa (replay histórico).
        with patch.object(emission, "COINBASE_ACTIVATION", 10**9):
            b = build_block(self.bc, [coinbase(self.leader, 999_999 * 1073741824)])
            self.assertTrue(self.bc.add_block(b, skip_zk=True))

    def test_producer_and_verifier_agree(self):
        # La función es determinista: dos llamadas dan el mismo valor.
        reg = self.bc.state_db.validator_registry
        self.assertEqual(expected_coinbase_reward(reg, 1, self.lh),
                         expected_coinbase_reward(reg, 1, self.lh))


if __name__ == "__main__":
    unittest.main()
