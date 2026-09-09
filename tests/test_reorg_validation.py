"""Fase 2: replace_chain valida cada bloque candidato (cierra el bypass)."""
import tempfile, unittest
from unittest.mock import patch
from blockchain.chain import Blockchain
from blockchain.storage import Storage
from blockchain.block import Block, Transaction
from blockchain import emission
from blockchain.emission import expected_coinbase_reward, m3_hash


def bc_with_validator():
    bc = Blockchain(Storage(f"{tempfile.mkdtemp()}/t.db"))
    m3 = [[[5, 5, 5, 5]]]; lh = m3_hash(m3)
    bc.state_db.validator_registry.validators[lh] = {
        "m3": m3, "m3_hash": lh, "endpoint": "x:1", "stake": 100 * 1073741824,
        "registered_at": 0, "slashed": False, "lambda_value": -0.6,
        "contraction_matrices": None}
    return bc, m3, lh


def block_with(bc, txs, index=1):
    b = Block(index=index, transactions=txs, previous_hash=bc.chain[-1].hash, timestamp=1.0)
    b.hash = b.calculate_hash()
    return b


def coinbase(rx, amt):
    return Transaction(sender_m3=[], receiver_m3=rx, amount=amt, signature_data={"type": "COINBASE"})


class ReorgValidationTests(unittest.TestCase):
    def setUp(self):
        self.bc, self.m3, self.lh = bc_with_validator()
        self.reward = expected_coinbase_reward(self.bc.state_db.validator_registry, 1, self.lh)

    def test_valid_block_accepted(self):
        with patch.object(emission, "COINBASE_ACTIVATION", 1):
            b = block_with(self.bc, [coinbase(self.m3, self.reward)])
            self.assertTrue(self.bc._validate_block_for_reorg(b))

    def test_tampered_hash_rejected(self):
        b = block_with(self.bc, [coinbase(self.m3, self.reward)])
        b.hash = "deadbeef" * 8  # hash manipulado
        self.assertFalse(self.bc._validate_block_for_reorg(b))

    def test_inflated_coinbase_rejected(self):
        with patch.object(emission, "COINBASE_ACTIVATION", 1):
            b = block_with(self.bc, [coinbase(self.m3, self.reward + 10**15)])
            self.assertFalse(self.bc._validate_block_for_reorg(b))

    def test_forged_protocol_op_rejected(self):
        # op de protocolo con firma inválida, post-activación
        with patch.object(emission, "COINBASE_ACTIVATION", 1), \
             patch("blockchain.protocol_auth.PROTOCOL_SIG_ACTIVATION", 1):
            tx = Transaction(sender_m3=self.m3, receiver_m3=self.m3, amount=0,
                             signature_data={"type": "FORGED"},
                             payload={"op": "VALIDATOR_EXIT"})
            b = block_with(self.bc, [coinbase(self.m3, self.reward), tx])
            with patch.object(self.bc, "_verify_signature", return_value=False):
                self.assertFalse(self.bc._validate_block_for_reorg(b))

    def test_forged_normal_tx_rejected(self):
        with patch.object(emission, "COINBASE_ACTIVATION", 1):
            tx = Transaction(sender_m3=[[[9]]], receiver_m3=[[[8]]], amount=5,
                             signature_data={"type": "X"})
            b = block_with(self.bc, [coinbase(self.m3, self.reward), tx])
            with patch.object(self.bc, "_verify_signature", return_value=False):
                self.assertFalse(self.bc._validate_block_for_reorg(b))

    def test_add_block_coinbase_still_works(self):
        # Regresión: el check de coinbase extraído sigue funcionando en add_block
        with patch.object(emission, "COINBASE_ACTIVATION", 1):
            b = block_with(self.bc, [coinbase(self.m3, self.reward + 10**15)])
            self.assertFalse(self.bc.add_block(b, skip_zk=True))


if __name__ == "__main__":
    unittest.main()
