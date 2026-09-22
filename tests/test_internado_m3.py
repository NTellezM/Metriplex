"""Internado de tensores m3 en la cadena (Blockchain._POOL_M3)."""
import copy
import tempfile
import unittest

from blockchain.block import Block, Transaction
from blockchain.chain import Blockchain
from blockchain.storage import Storage

PRODUCTOR_A = [[[1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12], [13, 14, 15, 16]]] * 4
PRODUCTOR_B = [[[21, 22, 23, 24], [25, 26, 27, 28], [29, 30, 31, 32], [33, 34, 35, 36]]] * 4


def cadena_en_disco(db, productores):
    bc = Blockchain(Storage(db))
    for i, rx in enumerate(productores, start=1):
        # json.loads-equivalente: cada bloque trae su PROPIA copia del tensor,
        # como ocurre al leerlo de SQLite.
        cb = Transaction(sender_m3=[], receiver_m3=copy.deepcopy(rx), amount=1,
                         signature_data={"type": "COINBASE"})
        b = Block(index=i, transactions=[cb], previous_hash=bc.chain[-1].hash,
                  timestamp=float(i + 1))
        b.hash = b.calculate_hash()
        bc.storage.save_block(b)
    return db


class InternadoM3Tests(unittest.TestCase):
    def setUp(self):
        Blockchain._POOL_M3.clear()
        self.db = cadena_en_disco(f"{tempfile.mkdtemp()}/t.db",
                                  [PRODUCTOR_A, PRODUCTOR_B] * 5)
        self.bc = Blockchain(Storage(self.db))
        self.cbs = [blk.transactions[0] for blk in self.bc.chain[1:]]

    def test_bloques_del_mismo_productor_comparten_el_objeto(self):
        de_a = [t.receiver_m3 for t in self.cbs if t.receiver_m3 == PRODUCTOR_A]
        self.assertEqual(len(de_a), 5)
        self.assertTrue(all(m is de_a[0] for m in de_a),
                        "los bloques de un mismo productor deben compartir el tensor")

    def test_el_pool_solo_tiene_los_tensores_distintos(self):
        self.assertEqual(len(Blockchain._POOL_M3), 2)

    def test_contenido_y_tx_id_intactos(self):
        for t in self.cbs:
            self.assertIn(t.receiver_m3, (PRODUCTOR_A, PRODUCTOR_B))
            self.assertEqual(t.tx_id, t.calculate_hash(),
                             "internar no debe cambiar el tx_id")

    def test_coinbase_sender_vacio_no_se_comparte(self):
        # [] es mutable: compartirlo entre todas las coinbase seria un riesgo
        # sin beneficio (56 bytes).
        vacios = [t.sender_m3 for t in self.cbs]
        self.assertEqual(vacios[0], [])
        self.assertFalse(vacios[0] is vacios[1])

    def test_revalidar_no_muta_los_tensores_compartidos(self):
        antes = copy.deepcopy(Blockchain._POOL_M3)
        for blk in self.bc.chain[1:]:
            blk.calculate_hash()
            for t in blk.transactions:
                t.calculate_hash()
                self.bc.validate_transaction(t, block_index=blk.index)
        self.assertEqual(Blockchain._POOL_M3, antes,
                         "la validacion modifico un tensor compartido")

    def test_transacciones_fuera_de_la_cadena_no_inflan_el_pool(self):
        # Una tx de la API que no llega a un bloque no debe entrar en el pool:
        # si no, se podria inflar sin limite con tensores aleatorios.
        n = len(Blockchain._POOL_M3)
        for k in range(50):
            Transaction(sender_m3=[[[k, k, k, k]]] * 4, receiver_m3=[[[k] * 4]] * 4,
                        amount=1, signature_data={})
        self.assertEqual(len(Blockchain._POOL_M3), n)


if __name__ == "__main__":
    unittest.main()
