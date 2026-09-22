"""Freno de la cascada de rollbacks de seguridad y tope de mensaje P2P.

Incidente del 2026-09-22. Con N_PROOF=2000, FULL_CHAIN (201 bloques) pesaba
~19,7 MB y excedia el tope de 16 MiB: se rechazaba y nodo3 no encontraba el
ancestro comun. El catch-up retrocedia 20 bloques "de seguridad" y reintentaba,
sin limite: 194 rollbacks seguidos borraron ~4.000 bloques de su disco.
"""
import asyncio
import io
import json
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from blockchain.block import Block
from network.p2p import CAFNode


class Writer:
    def __init__(self):
        self.data, self.cerrado = b"", False

    def write(self, data):
        self.data += data

    async def drain(self):
        pass

    def close(self):
        self.cerrado = True

    async def wait_closed(self):
        pass


def cadena(n):
    ch = [Block(0, [], "0", timestamp=1)]
    ch[0].hash = "h0"
    for i in range(1, n):
        b = Block(i, [], ch[-1].hash, timestamp=i + 1)
        b.hash = f"h{i}"
        ch.append(b)
    return ch


class CascadaTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.chain = cadena(400)

        def add(block, **kw):
            if block.index != self.chain[-1].index + 1 or block.previous_hash != self.chain[-1].hash:
                return False
            self.chain.append(block)
            return True

        def rollback(idx):
            del self.chain[idx + 1:]
            return True

        bc = SimpleNamespace(chain=self.chain, validator_registry=SimpleNamespace(validators={}),
                             add_block=Mock(side_effect=add), rollback_to=Mock(side_effect=rollback))
        self.bc = bc
        self.node = CAFNode("127.0.0.1", 65432, bc, SimpleNamespace(remove_mined_transactions=Mock()))
        self.node.request_sync = AsyncMock()

    async def entregar(self, payload):
        reader = asyncio.StreamReader()
        reader.feed_data(json.dumps(payload).encode())
        reader.feed_eof()
        w = Writer()
        with redirect_stdout(io.StringIO()) as out:
            await self.node.handle_client(reader, w)
        return w, out.getvalue()

    def segmento_huerfano(self):
        # Bloque siguiente a la punta pero con un previous_hash que no existe:
        # add_block lo rechaza y el ancestro no aparece en los ultimos 30.
        tip = self.chain[-1]
        return {"type": "CHAIN_SEGMENT", "peer_height": tip.index + 1, "blocks": [{
            "index": tip.index + 1, "hash": "x", "previous_hash": "no-existe",
            "timestamp": tip.timestamp + 1, "nonce": 0, "transactions": []}]}

    async def test_la_cascada_se_detiene_en_el_tope(self):
        tope = CAFNode.MAX_ROLLBACKS_SEGURIDAD
        for _ in range(tope + 5):
            await self.entregar(self.segmento_huerfano())
        self.assertEqual(self.bc.rollback_to.call_count, tope,
                         "no debe hacer mas rollbacks de seguridad que el tope")
        self.assertEqual(len(self.chain), 400 - tope * 20,
                         "la cadena solo puede perder tope x 20 bloques")

    async def test_el_freno_avisa_y_cierra_la_conexion(self):
        for _ in range(CAFNode.MAX_ROLLBACKS_SEGURIDAD):
            await self.entregar(self.segmento_huerfano())
        w, salida = await self.entregar(self.segmento_huerfano())
        self.assertIn("DETENIDO", salida)
        self.assertTrue(w.cerrado, "el freno no debe dejar la conexion abierta")

    async def test_integrar_un_bloque_reinicia_el_contador(self):
        for _ in range(3):
            await self.entregar(self.segmento_huerfano())
        self.assertEqual(self.node._rollbacks_seguridad, 3)
        tip = self.chain[-1]
        await self.entregar({"type": "CHAIN_SEGMENT", "peer_height": tip.index + 1, "blocks": [{
            "index": tip.index + 1, "hash": "ok", "previous_hash": tip.hash,
            "timestamp": tip.timestamp + 1, "nonce": 0, "transactions": []}]})
        self.assertEqual(self.node._rollbacks_seguridad, 0)

    async def test_un_full_chain_de_20_mb_ya_no_se_rechaza(self):
        # FULL_CHAIN real con N_PROOF=2000: ~19,7 MB. Antes excedia 16 MiB.
        relleno = "0" * (20 * 1024 * 1024)
        _, salida = await self.entregar({"type": "PING", "relleno": relleno})
        self.assertNotIn("excede", salida)

    async def test_mas_alla_del_tope_si_se_rechaza(self):
        relleno = "0" * (33 * 1024 * 1024)
        _, salida = await self.entregar({"type": "PING", "relleno": relleno})
        self.assertIn("excede", salida)


if __name__ == "__main__":
    unittest.main()
