"""
Regresión: acuñación pública ilimitada vía TX sin remitente (2026-09-08).

validate_transaction() acepta toda TX con sender_m3 vacío sin firma, sin ZK y
sin verificar saldo — es la vía por la que el minero se paga la recompensa de
bloque. El mempool no filtraba esas TX, y el mempool es el único punto de
entrada tanto de POST /transaction como del gossip P2P NEW_TX, así que
cualquiera podía acuñar MPX arbitrario contra el nodo público.
"""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from blockchain.block import Transaction
from network.mempool import Mempool
from api.server import create_api_app


def make_mempool(tmpdir):
    # validate_transaction siempre acepta: aísla el test al filtro del mempool.
    chain = SimpleNamespace(chain=[SimpleNamespace(index=0)],
                            validate_transaction=Mock(return_value=True))
    return Mempool(chain, persist_path=str(Path(tmpdir) / "mempool.json"))


def tx(sender, amount=1000):
    # tx_id = sha256(sender, receiver, amount, fee, payload) — signature_data
    # no entra en el hash, así que variar el monto es lo que da TX distintas.
    return Transaction(sender_m3=sender, receiver_m3=[[[1]]], amount=amount,
                       signature_data={"type": "COINBASE"})


class CoinbaseInjectionTests(unittest.TestCase):
    def test_coinbase_from_outside_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            pool = make_mempool(tmp)
            for empty in ([], None):
                self.assertFalse(pool.add_transaction(tx(empty, amount=10**12)))
            self.assertEqual(pool.pending_transactions, {})

    def test_normal_transaction_still_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            pool = make_mempool(tmp)
            self.assertTrue(pool.add_transaction(tx([[[7]]])))
            self.assertEqual(len(pool.pending_transactions), 1)

    def test_antispam_still_caps_pending_per_sender(self):
        with tempfile.TemporaryDirectory() as tmp:
            pool = make_mempool(tmp)
            accepted = [pool.add_transaction(tx([[[7]]], amount=100 + i)) for i in range(7)]
            self.assertEqual(accepted, [True] * 5 + [False] * 2)

    def test_public_mint_endpoints_are_gone(self):
        chain = SimpleNamespace(chain=[SimpleNamespace(index=1, hash="a" * 64)],
                                validator_registry=SimpleNamespace(validators={}))
        node = SimpleNamespace(host_public="127.0.0.1", port=65432, peers=set(),
                               permanent_peers=set(), authenticated_peers={})
        app = create_api_app(chain, SimpleNamespace(pending_transactions={}), node)
        paths = {r.path for r in app.routes}
        self.assertNotIn("/faucet", paths)
        self.assertNotIn("/mine", paths)
        # Lo que el sitio sí usa debe seguir existiendo.
        for kept in ("/network", "/blocks", "/transaction", "/validators"):
            self.assertIn(kept, paths)


if __name__ == "__main__":
    unittest.main()
