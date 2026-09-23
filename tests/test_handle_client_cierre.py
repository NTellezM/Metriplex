"""handle_client debe cerrar la conexión en TODOS los caminos.

Antes, el cierre estaba fuera del try y sin finally: los return tempranos
(requester inválido, CHAIN_SEGMENT vacío, NEW_BLOCK ya conocido,
STATUS_REQUEST) salían sin cerrar el writer y dejaban el socket colgado hasta
el timeout del peer. Con muchos mensajes de esos, los descriptores se
acumulaban. Este test recorre cada camino y exige que el writer quede cerrado.
"""
import asyncio
import io
import json
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock

from blockchain.block import Block
from network.p2p import CAFNode


class Writer:
    def __init__(self, peer_ip="9.9.9.9"):
        self.data, self.cerrado, self.wait_cerrado, self.peer_ip = b"", False, False, peer_ip

    def get_extra_info(self, clave):
        return (self.peer_ip, 50000) if clave == "peername" else None

    def write(self, d):
        self.data += d

    async def drain(self):
        pass

    def close(self):
        self.cerrado = True

    async def wait_closed(self):
        self.wait_cerrado = True


def cadena(n):
    ch = [Block(0, [], "0", timestamp=1)]
    ch[0].hash = "h0"
    for i in range(1, n):
        b = Block(i, [], ch[-1].hash, timestamp=i + 1)
        b.hash = f"h{i}"
        ch.append(b)
    return ch


class CierreHandleClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.chain = cadena(20)
        self.bc = SimpleNamespace(
            chain=self.chain,
            validator_registry=SimpleNamespace(validators={}),
            add_block=Mock(return_value=True),
            rollback_to=Mock(return_value=True),
        )
        self.node = CAFNode("127.0.0.1", 65432, self.bc,
                            SimpleNamespace(remove_mined_transactions=Mock()))

    async def entregar(self, payload, peer_ip="9.9.9.9"):
        r = asyncio.StreamReader()
        r.feed_data(json.dumps(payload).encode())
        r.feed_eof()
        w = Writer(peer_ip)
        with redirect_stdout(io.StringIO()):
            await self.node.handle_client(r, w)
        return w

    async def _afirmar_cerrado(self, payload, peer_ip="9.9.9.9"):
        w = await self.entregar(payload, peer_ip)
        self.assertTrue(w.cerrado, "el writer no se cerró")
        self.assertTrue(w.wait_cerrado, "no se esperó al cierre del writer")

    # ── los return tempranos que antes filtraban ────────────────────────────
    async def test_request_chain_sync_requester_invalido(self):
        # requester no coincide con la IP real → return temprano
        await self._afirmar_cerrado(
            {"type": "REQUEST_CHAIN_SYNC", "last_index": 1, "requester": "1.2.3.4:65000"})

    async def test_request_full_chain_requester_invalido(self):
        await self._afirmar_cerrado(
            {"type": "REQUEST_FULL_CHAIN", "requester": "1.2.3.4:65000"})

    async def test_chain_segment_vacio(self):
        await self._afirmar_cerrado({"type": "CHAIN_SEGMENT", "blocks": []})

    async def test_status_request_escribe_y_cierra(self):
        w = await self.entregar({"type": "STATUS_REQUEST"})
        self.assertTrue(w.data, "STATUS_REQUEST debe responder algo")
        self.assertTrue(w.cerrado and w.wait_cerrado, "STATUS_REQUEST salió sin cerrar")

    async def test_new_block_ya_conocido(self):
        b = self.chain[5]
        await self._afirmar_cerrado({"type": "NEW_BLOCK", "data": {
            "index": b.index, "hash": b.hash, "previous_hash": b.previous_hash,
            "timestamp": b.timestamp, "transactions": []}})

    # ── caminos normales y de error también cierran ─────────────────────────
    async def test_mensaje_desconocido(self):
        await self._afirmar_cerrado({"type": "NO_EXISTE"})

    async def test_json_invalido(self):
        r = asyncio.StreamReader()
        r.feed_data(b"{esto no es json")
        r.feed_eof()
        w = Writer()
        with redirect_stdout(io.StringIO()):
            await self.node.handle_client(r, w)
        self.assertTrue(w.cerrado and w.wait_cerrado)

    async def test_datos_binarios(self):
        r = asyncio.StreamReader()
        r.feed_data(b"\xff\xfe\x00 no utf8}")
        r.feed_eof()
        w = Writer()
        with redirect_stdout(io.StringIO()):
            await self.node.handle_client(r, w)
        self.assertTrue(w.cerrado and w.wait_cerrado)

    async def test_una_excepcion_interna_igual_cierra(self):
        # NEW_BLOCK con data mal formada revienta dentro del try: el finally
        # debe cerrar igual.
        await self._afirmar_cerrado({"type": "NEW_BLOCK", "data": {"index": 5}})


if __name__ == "__main__":
    unittest.main()
