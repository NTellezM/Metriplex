import os
import tempfile
import unittest
from unittest.mock import patch

from blockchain.block import Block, Transaction
from blockchain.chain import Blockchain
from blockchain.rules import CHAIN_ID, TX_V2_ACTIVATION
from blockchain.storage import Storage
from blockchain.tx_canonical import canonical_tx_hash_v2
from blockchain.emission import expected_coinbase_reward


class CriticalConsensusTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.storage = Storage(self.path)
        self.chain = Blockchain(self.storage)
        self.sender = [[[1]]]
        self.receiver = [[[2]]]
        self.storage.credit(self.chain.get_tensor_hash(self.sender), 100)

    def tearDown(self):
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(self.path + suffix)
            except FileNotFoundError:
                pass

    def test_negative_amount_and_fee_are_rejected(self):
        negative_amount = Transaction(self.sender, self.receiver, -1, {})
        negative_fee = Transaction(self.sender, self.receiver, 1, {}, fee=-2)
        self.assertFalse(self.chain.validate_transaction(negative_amount, 1))
        self.assertFalse(self.chain.validate_transaction(negative_fee, 1))

    def test_storage_rejects_integer_overflow(self):
        account = "f" * 64
        self.storage.credit(account, 2**63 - 1)
        with self.assertRaises(ValueError):
            self.storage.credit(account, 1)
        self.assertEqual(self.storage.get_balance(account), 2**63 - 1)

    def test_snapshot_restores_contract_state(self):
        self.storage.set_contract_state("contract", "key", "value")
        self.storage.save_snapshot(0, "0" * 64, {})
        snapshot = self.storage.get_latest_snapshot(0)
        self.storage.clear_all()
        self.storage.restore_snapshot(snapshot)
        self.assertEqual(self.storage.get_contract_state("contract", "key"), "value")

    def test_block_application_is_atomic_on_cumulative_overspend(self):
        first = Transaction(self.sender, self.receiver, 70, {})
        second = Transaction(self.sender, [[[3]]], 70, {})
        block = Block(1, [first, second], self.chain.chain[-1].hash)
        with patch.object(self.chain, "validate_transaction", return_value=True):
            self.assertFalse(self.chain.add_block(block))
        self.assertEqual(self.storage.get_balance(self.chain.get_tensor_hash(self.sender)), 100)
        self.assertEqual(self.storage.get_balance(self.chain.get_tensor_hash(self.receiver)), 0)
        self.assertEqual(self.chain.chain[-1].index, 0)

    def test_confirmed_transaction_cannot_be_replayed(self):
        tx = Transaction(self.sender, self.receiver, 10, {})
        first = Block(1, [tx], self.chain.chain[-1].hash)
        with patch.object(self.chain, "validate_transaction", return_value=True):
            self.assertTrue(self.chain.add_block(first))
            replay = Block(2, [tx], first.hash)
            self.assertFalse(self.chain.add_block(replay))

    def test_v2_signature_commits_payload_and_network(self):
        payload = {
            "version": 2,
            "chain_id": CHAIN_ID,
            "nonce": "a" * 32,
            "target_eth_address": "0x" + "1" * 40,
        }
        tx = Transaction(self.sender, self.receiver, 1, {}, payload)
        expected = canonical_tx_hash_v2(self.sender, self.receiver, 1, 0, payload)
        with patch.object(self.chain, "_verify_signature", return_value=True) as verify:
            self.assertTrue(self.chain.validate_transaction(tx, TX_V2_ACTIVATION))
        self.assertEqual(verify.call_args.args[2], expected)
        changed = dict(payload, target_eth_address="0x" + "2" * 40)
        self.assertNotEqual(expected, canonical_tx_hash_v2(self.sender, self.receiver, 1, 0, changed))

    def test_invalid_reorg_leaves_live_state_untouched(self):
        local_tx = Transaction([], self.receiver, 10, {"type": "COINBASE"})
        local = Block(1, [local_tx], self.chain.chain[-1].hash)
        self.assertTrue(self.chain.add_block(local, skip_zk=True))
        before = self.storage.get_balance(self.chain.get_tensor_hash(self.receiver))
        bad = Block(1, [Transaction([], [[[9]]], 20, {"type": "COINBASE"})], self.chain.chain[0].hash)
        bad.hash = "f" * 64
        remote = [self.chain.chain[0], bad, Block(2, [], bad.hash)]
        self.assertFalse(self.chain.replace_chain(remote))
        self.assertEqual(self.chain.chain[-1].hash, local.hash)
        self.assertEqual(self.storage.get_balance(self.chain.get_tensor_hash(self.receiver)), before)

    def test_validator_exit_cannot_select_an_arbitrary_vault(self):
        sender_hash = self.chain.get_tensor_hash(self.sender)
        self.chain.validator_registry.validators[sender_hash] = {
            "m3": self.sender, "m3_hash": sender_hash, "endpoint": "x:1",
            "stake": 100, "registered_at": 0, "slashed": False,
            "lambda_value": -0.5,
        }
        payload = {
            "op": "VALIDATOR_EXIT", "version": 2, "chain_id": CHAIN_ID,
            "nonce": "b" * 32,
        }
        tx = Transaction(self.sender, self.receiver, 0, {}, payload)
        with patch.object(self.chain, "_verify_signature", return_value=True):
            self.assertFalse(self.chain.validate_transaction(tx, TX_V2_ACTIVATION))

    def test_post_activation_block_requires_leader_proof(self):
        import time
        validator_hash = self.chain.get_tensor_hash(self.sender)
        entry = {
            "m3": self.sender, "m3_hash": validator_hash, "endpoint": "x:1",
            "stake": 100, "registered_at": 0, "slashed": False,
            "lambda_value": -0.5,
        }
        self.chain.validator_registry.validators[validator_hash] = entry
        self.chain.validator_registry._record(0, validator_hash, entry)
        reward = expected_coinbase_reward(
            self.chain.validator_registry, TX_V2_ACTIVATION, validator_hash
        )
        coinbase = Transaction([], self.sender, reward, {"type": "COINBASE"})
        block = Block(
            TX_V2_ACTIVATION, [coinbase], self.chain.chain[-1].hash,
            timestamp=time.time(),
        )
        self.assertFalse(self.chain._check_block_coinbase(block))
        with patch.object(self.chain, "_verify_signature", return_value=True):
            self.assertTrue(self.chain._check_block_coinbase(block))


if __name__ == "__main__":
    unittest.main()
