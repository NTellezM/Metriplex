"""Resolucion de forks por FULL_CHAIN y su version paginada."""
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
    def __init__(self, peer_ip="127.0.0.1"):
        self.data, self.cerrado, self.peer_ip = b"", False, peer_ip

    def get_extra_info(self, clave):
        return (self.peer_ip, 50000) if clave == "peername" else None

    def write(self, d):
        self.data += d

    async def drain(self):
        pass

    def close(self):
        self.cerrado = True

    async def wait_closed(self):
        pass


def cadena(n, pref="h"):
    ch = [Block(0, [], "0", timestamp=1)]
    ch[0].hash = f"{pref}0"
    for i in range(1, n):
        b = Block(i, [], ch[-1].hash, timestamp=i + 1)
        b.hash = f"{pref}{i}"
        ch.append(b)
    return ch


def bloque_dict(i, prev, h):
    return {"index": i, "hash": h, "previous_hash": prev, "timestamp": i + 1,
            "nonce": 0, "transactions": []}


class FullChainTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.chain = cadena(50)
        self.bc = SimpleNamespace(chain=self.chain, validator_registry=SimpleNamespace(validators={}),
                                  replace_chain=Mock(return_value=True))
        self.node = CAFNode("127.0.0.1", 65432, self.bc,
                            SimpleNamespace(remove_mined_transactions=Mock()))

    async def entregar(self, payload, peer_ip="127.0.0.1"):
        r = asyncio.StreamReader()
        r.feed_data(json.dumps(payload).encode())
        r.feed_eof()
        with redirect_stdout(io.StringIO()):
            await self.node.handle_client(r, Writer(peer_ip))

    def competidora(self, base, n):
        # n bloques de una rama alternativa que cuelga del bloque base-1
        prev = self.chain[base - 1].hash
        out = []
        for k in range(n):
            h = f"alt{base + k}"
            out.append(bloque_dict(base + k, prev, h))
            prev = h
        return out

    def cadena_pasada(self):
        self.assertTrue(self.bc.replace_chain.called, "no se llamo a replace_chain")
        return self.bc.replace_chain.call_args.args[0]

    # ── FULL_CHAIN de un solo mensaje (comportamiento existente) ────────────
    async def test_full_chain_construye_la_cadena_candidata(self):
        base = 40
        await self.entregar({"type": "FULL_CHAIN", "base_index": base,
                             "blocks": self.competidora(base, 12)})
        nueva = self.cadena_pasada()
        self.assertEqual(len(nueva), base + 12)
        self.assertEqual([b.hash for b in nueva[:base]], [b.hash for b in self.chain[:base]])
        self.assertEqual([b.hash for b in nueva[base:]], [f"alt{base + k}" for k in range(12)])

    async def test_full_chain_base_index_fuera_de_rango_se_ignora(self):
        await self.entregar({"type": "FULL_CHAIN", "base_index": 999, "blocks": []})
        self.assertFalse(self.bc.replace_chain.called)

    # ── FULL_CHAIN paginado ─────────────────────────────────────────────────
    def paginas(self, base, bloques, n, tip="tipX"):
        tam = -(-len(bloques) // n)
        trozos = [bloques[k * tam:(k + 1) * tam] for k in range(n)]
        return [{"type": "FULL_CHAIN_PAGE", "base_index": base, "tip": tip,
                 "page": k, "pages": n, "blocks": t} for k, t in enumerate(trozos)]

    async def hashes_via_un_mensaje(self, base, bloques):
        self.bc.replace_chain.reset_mock()
        await self.entregar({"type": "FULL_CHAIN", "base_index": base, "blocks": bloques})
        return [b.hash for b in self.cadena_pasada()]

    async def test_paginado_equivale_a_un_solo_mensaje(self):
        base, bloques = 30, self.competidora(30, 20)
        esperado = await self.hashes_via_un_mensaje(base, bloques)
        self.bc.replace_chain.reset_mock()
        for pag in self.paginas(base, bloques, 4):
            await self.entregar(pag)
        self.assertEqual([b.hash for b in self.cadena_pasada()], esperado,
                         "paginado debe dar la misma cadena candidata que un mensaje")

    async def test_paginas_desordenadas_se_reensamblan_en_orden(self):
        base, bloques = 30, self.competidora(30, 20)
        esperado = await self.hashes_via_un_mensaje(base, bloques)
        self.bc.replace_chain.reset_mock()
        pags = self.paginas(base, bloques, 4)
        for pag in [pags[2], pags[0], pags[3], pags[1]]:
            await self.entregar(pag)
        self.assertEqual([b.hash for b in self.cadena_pasada()], esperado)

    async def test_pagina_duplicada_no_cambia_el_resultado(self):
        base, bloques = 30, self.competidora(30, 20)
        esperado = await self.hashes_via_un_mensaje(base, bloques)
        self.bc.replace_chain.reset_mock()
        pags = self.paginas(base, bloques, 3)
        for pag in [pags[0], pags[0], pags[1], pags[2]]:
            await self.entregar(pag)
        self.assertEqual(self.bc.replace_chain.call_count, 1)
        self.assertEqual([b.hash for b in self.cadena_pasada()], esperado)

    async def test_conjunto_incompleto_no_decide_nada(self):
        pags = self.paginas(30, self.competidora(30, 20), 4)
        for pag in pags[:3]:
            await self.entregar(pag)
        self.assertFalse(self.bc.replace_chain.called)

    async def test_total_de_paginas_incoherente_descarta_el_conjunto(self):
        pags = self.paginas(30, self.competidora(30, 20), 4)
        await self.entregar(pags[0])
        falsa = dict(pags[1], pages=5)            # otro total para la misma clave
        await self.entregar(falsa)
        for pag in pags[2:]:
            await self.entregar(pag)
        self.assertFalse(self.bc.replace_chain.called)

    async def test_paginas_invalidas_se_ignoran(self):
        for malo in [{"page": 4, "pages": 4}, {"page": -1}, {"pages": 0, "page": 0},
                     {"pages": CAFNode.FULL_CHAIN_PAGES_MAX + 1, "page": 0},
                     {"base_index": "x"}, {"tip": 7}, {"blocks": "no-lista"}]:
            await self.entregar(dict({"type": "FULL_CHAIN_PAGE", "base_index": 30,
                                      "tip": "t", "page": 0, "pages": 2, "blocks": []}, **malo))
        self.assertEqual(self.node._full_chain_parcial, {},
                         "una pagina invalida no debe entrar en el buffer")
        self.assertFalse(self.bc.replace_chain.called)

    async def test_el_buffer_de_conjuntos_incompletos_esta_acotado(self):
        for t in range(CAFNode.FULL_CHAIN_BUFFER_MAX + 10):
            await self.entregar(self.paginas(30, self.competidora(30, 20), 4, tip=f"t{t}")[0])
        self.assertLessEqual(len(self.node._full_chain_parcial), CAFNode.FULL_CHAIN_BUFFER_MAX)

    async def test_conjunto_caducado_se_olvida(self):
        pags = self.paginas(30, self.competidora(30, 20), 2)
        await self.entregar(pags[0])
        for v in self.node._full_chain_parcial.values():
            v["ts"] -= CAFNode.FULL_CHAIN_TTL + 1   # envejecer
        await self.entregar(pags[1])               # llega tarde: ya no completa
        self.assertFalse(self.bc.replace_chain.called)

    # ── emisor ─────────────────────────────────────────────────────────────
    def test_paginar_respeta_orden_y_presupuesto(self):
        bloques = self.competidora(30, 20)
        self.node.FULL_CHAIN_PAGINA_BYTES = len(json.dumps(bloques[0])) * 3 + 10
        pags = self.node._paginar_bloques(bloques)
        self.assertGreater(len(pags), 1)
        self.assertEqual([b for p in pags for b in p], bloques, "no debe perder ni reordenar")
        for p in pags:
            self.assertLessEqual(sum(len(json.dumps(b)) for b in p),
                                 self.node.FULL_CHAIN_PAGINA_BYTES)

    def test_bloque_mayor_que_el_presupuesto_va_solo(self):
        bloques = self.competidora(30, 3)
        self.node.FULL_CHAIN_PAGINA_BYTES = 10
        self.assertEqual([len(p) for p in self.node._paginar_bloques(bloques)], [1, 1, 1])

    async def test_emisor_manda_formato_clasico_si_cabe(self):
        enviados = await self.capturar_respuesta()
        self.assertEqual([m["type"] for m in enviados], ["FULL_CHAIN"])

    async def test_emisor_pagina_si_no_cabe(self):
        self.node.FULL_CHAIN_PAGINA_BYTES = 400
        enviados = await self.capturar_respuesta()
        self.assertGreater(len(enviados), 1)
        self.assertTrue(all(m["type"] == "FULL_CHAIN_PAGE" for m in enviados))
        self.assertEqual(sorted(m["page"] for m in enviados), list(range(len(enviados))))
        # y reensamblado debe reproducir exactamente los bloques enviados
        todos = [b["hash"] for m in sorted(enviados, key=lambda m: m["page"]) for b in m["blocks"]]
        self.assertEqual(todos, [b.hash for b in self.chain[enviados[0]["base_index"]:]])

    async def capturar_respuesta(self):
        from unittest.mock import patch
        enviados = []

        class W(Writer):
            def write(self, d):
                enviados.append(json.loads(d))

        async def abrir(host, port):
            return asyncio.StreamReader(), W()

        with patch("network.p2p.asyncio.open_connection", side_effect=abrir):
            # validated_requester exige que el requester sea la IP real que
            # conecta (anti-suplantacion): se cumple, no se esquiva.
            await self.entregar({"type": "REQUEST_FULL_CHAIN", "requester": "1.2.3.4:65000"},
                                peer_ip="1.2.3.4")
        return enviados

    async def test_requester_suplantado_no_recibe_nada(self):
        from unittest.mock import patch
        abierto = []

        async def abrir(host, port):
            abierto.append((host, port))
            return asyncio.StreamReader(), Writer()

        with patch("network.p2p.asyncio.open_connection", side_effect=abrir):
            # dice ser 1.2.3.4 pero conecta desde 9.9.9.9
            await self.entregar({"type": "REQUEST_FULL_CHAIN", "requester": "1.2.3.4:65000"},
                                peer_ip="9.9.9.9")
        self.assertEqual(abierto, [], "no debe enviar la cadena a un requester suplantado")


if __name__ == "__main__":
    unittest.main()
