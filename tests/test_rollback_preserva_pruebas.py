"""rollback_to no debe destruir las pruebas ZK guardadas en disco.

Regresion del 2026-09-21. El parche de memoria (VENTANA_PRUEBAS) quita x_final
de los bloques en RAM que quedan fuera de la ventana de reorg. rollback_to
hacia clear_all() y reescribia los bloques conservados DESDE RAM, asi que
persistia esas versiones aligeradas: en nodo3, cinco rollbacks dejaron 7.508
coinbases sin x_final en disco, con el hash original apuntando a datos que ya
no existian.
"""
import json
import tempfile
import unittest
from unittest.mock import patch

from blockchain.block import Block, Transaction
from blockchain.chain import Blockchain
from blockchain.storage import Storage

N_BLOQUES = 30
VENTANA = 5


def coinbase_con_prueba(i):
    return Transaction(
        sender_m3=[],
        receiver_m3=[[[i, i, i, i]]],
        amount=1,
        signature_data={"x_final": [[i, i + 1, i + 2, i + 3]] * 4, "pi": f"pi{i}"},
    )


def construir_cadena(db):
    bc = Blockchain(Storage(db))
    for i in range(1, N_BLOQUES):
        b = Block(index=i, transactions=[coinbase_con_prueba(i)],
                  previous_hash=bc.chain[-1].hash, timestamp=float(i + 1))
        b.hash = b.calculate_hash()
        bc.storage.save_block(b)
        bc.chain.append(b)
    return bc


def coinbase_en_disco(db, idx):
    fila = Storage(db)._conn().execute(
        "SELECT transactions FROM blocks WHERE block_index = ?", (idx,)).fetchone()
    if fila is None:
        return None
    txs = [t for t in json.loads(fila[0]) if not t.get("sender_m3")]
    return (txs[0].get("signature_data") or {}) if txs else {}


class RollbackPreservaPruebasTests(unittest.TestCase):
    def setUp(self):
        self.db = f"{tempfile.mkdtemp()}/t.db"
        construir_cadena(self.db)
        # Recargar desde disco: aqui actua el descarte de VENTANA_PRUEBAS.
        with patch.object(Blockchain, "VENTANA_PRUEBAS", VENTANA):
            self.bc = Blockchain(Storage(self.db))

    def test_el_descarte_en_ram_esta_activo(self):
        # Premisa del test: sin esto no se reproduce el escenario del bug.
        viejo = self.bc.chain[1].transactions[0].signature_data
        reciente = self.bc.chain[-1].transactions[0].signature_data
        self.assertNotIn("x_final", viejo, "los bloques viejos deben ir aligerados en RAM")
        self.assertIn("x_final", reciente, "los recientes conservan la prueba")

    def test_rollback_conserva_x_final_en_disco(self):
        objetivo = N_BLOQUES - 4
        self.assertTrue(self.bc.rollback_to(objetivo))

        for idx in range(1, objetivo + 1):
            sig = coinbase_en_disco(self.db, idx)
            self.assertIsNotNone(sig, f"el bloque {idx} debe seguir en disco")
            self.assertIn("x_final", sig,
                          f"el bloque {idx} perdio x_final en disco tras el rollback")

    def test_rollback_quita_los_bloques_por_encima(self):
        objetivo = N_BLOQUES - 4
        self.bc.rollback_to(objetivo)
        for idx in range(objetivo + 1, N_BLOQUES):
            self.assertIsNone(coinbase_en_disco(self.db, idx),
                              f"el bloque {idx} debio eliminarse")
        self.assertEqual(len(self.bc.chain) - 1, objetivo)


if __name__ == "__main__":
    unittest.main()
