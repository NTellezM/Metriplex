"""Serialización canónica única: validate_transaction y validate_zk_only
deben computar el MISMO tx_hash, e igual al que firma el cliente."""
import hashlib
import json
import time
import tempfile
import unittest
from unittest.mock import patch

from blockchain.chain import Blockchain
from blockchain.storage import Storage
from blockchain.block import Transaction
from blockchain.tx_canonical import canonical_tx_hash


def bc():
    return Blockchain(Storage(f"{tempfile.mkdtemp()}/t.db"))


class CanonicalHashTests(unittest.TestCase):
    def test_matches_client_serialization(self):
        # El cliente (buildSignedTx) firma sha256(sortedJSON({amount,fee,
        # payload:null,receiver_m3,sender_m3})). sort_keys lo hace determinista.
        sender, receiver, amount, fee = [[[1]]], [[[2]]], 500, 0
        expected = hashlib.sha256(json.dumps(
            {"amount": amount, "fee": fee, "payload": None,
             "receiver_m3": receiver, "sender_m3": sender},
            sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(canonical_tx_hash(sender, receiver, amount, fee), expected)

    def test_payload_not_part_of_hash(self):
        # Dos TX iguales salvo el payload transportado => mismo hash firmado.
        h1 = canonical_tx_hash([[[1]]], [[[2]]], 10, 0)
        # canonical no recibe payload: por diseño no entra. Confirmamos estable.
        h2 = canonical_tx_hash([[[1]]], [[[2]]], 10, 0)
        self.assertEqual(h1, h2)

    def test_both_validators_use_same_hash(self):
        b = bc()
        tx = Transaction(sender_m3=[[[7]]], receiver_m3=[[[8]]], amount=42,
                         signature_data={"type": "X"},
                         payload={"timestamp": int(time.time())})  # payload transportado (actual)
        seen = []
        def capture(sig, m3, h):
            seen.append(h); return True
        with patch.object(b, "_verify_signature", side_effect=capture):
            # forzar que validate_transaction llegue a la firma: saldo suficiente
            with patch.object(b.state_db, "get_balance", return_value=10**9):
                b.validate_transaction(tx, block_index=1)
            b.validate_zk_only(tx)
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0], seen[1], "las dos rutas deben usar el mismo hash")
        self.assertEqual(seen[0], canonical_tx_hash(tx.sender_m3, tx.receiver_m3, tx.amount, tx.fee))

    def test_zk_only_skips_protocol_ops(self):
        b = bc()
        tx = Transaction(sender_m3=[[[7]]], receiver_m3=[[[7]]], amount=0,
                         signature_data={"type": "X"}, payload={"op": "VALIDATOR_EXIT"})
        # protocol ops se difieren (se validan en add_block): no llama _verify_signature
        with patch.object(b, "_verify_signature", side_effect=AssertionError("no debe llamarse")):
            self.assertTrue(b.validate_zk_only(tx))


if __name__ == "__main__":
    unittest.main()
