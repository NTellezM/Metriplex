# SPDX-License-Identifier: MIT
#
# Metriplex Protocol
# Copyright (c) 2025-2026 NTellezM (Nelson Tellez)
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software to use, copy, modify, and distribute this
# software under the terms of the MIT License.
#
"""
Módulo de red Peer-to-Peer para el protocolo CAF.
Implementa descubrimiento de pares, sincronización histórica (Block Sync) y propagación de estado.
"""

import asyncio
import json

import requests
from blockchain.block import Block, Transaction
from blockchain.chain import Blockchain

from network.mempool import Mempool


class CAFNode:
    def __init__(self, host: str, port: int, blockchain: Blockchain, mempool: Mempool, host_public: str = None):
        self.host = host
        self.port = port
        self.host_public = host_public or host
        self.blockchain = blockchain
        self.mempool = mempool
        self.peers = set()
        self.syncing = False
        # --- NUEVO: Control de resiliencia P2P ---
        self.banned_peers = set()
        self.peer_failures = {}
        self.max_failures = 3

    def penalize_peer(self, peer: str):
        """Aísla nodos caídos o que envían respuestas inválidas."""
        self.peer_failures[peer] = self.peer_failures.get(peer, 0) + 1
        if self.peer_failures[peer] >= self.max_failures:
            print(f"[Red P2P] Nodo inalcanzable. Expulsando: {peer}")
            if peer in self.peers:
                self.peers.remove(peer)
            self.banned_peers.add(peer)

    async def start_server(self):
        server = await asyncio.start_server(self.handle_client, self.host, self.port)
        addr = server.sockets[0].getsockname()
        print(f"[Red] Nodo P2P escuchando en {addr[0]}:{addr[1]}")

        # Iniciar descubrimiento y sincronización al levantar el nodo
        asyncio.create_task(self.announce_to_peers())

        async with server:
            await server.serve_forever()

    async def announce_to_peers(self):
        """Envía un handshake inicial a los pares y solicita sincronización."""
        await asyncio.sleep(1)
        if self.peers:
            # 1. Informar existencia
            handshake = json.dumps(
                {"type": "HANDSHAKE", "data": f"{self.host_public}:{self.port}"}
            ).encode()
            await self._broadcast(handshake)

            # 2. FASE F1: Solicitar sincronización del historial
            # Llamamos al método centralizado en lugar de armar el JSON a mano
            await self.request_sync()

    async def request_sync(self):
        """Pide a los pares los bloques posteriores a la altura local."""
        if self.syncing:
            return

        local_height = self.blockchain.chain[-1].index
        print(f"[Red] Solicitando sincronización desde el bloque {local_height}...")
        self.syncing = True

        req_msg = json.dumps(
            {
                "type": "REQUEST_CHAIN_SYNC",
                "last_index": local_height,
                "requester": f"{self.host_public}:{self.port}",
            }
        ).encode()
        await self._broadcast(req_msg)

        # Desbloquear la bandera después de un tiempo razonable
        await asyncio.sleep(5)
        self.syncing = False

    async def handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        # Buffer de 10 MB para soportar segmentos enteros de cadena (Block Sync)
        data = await reader.read(10485760)
        if len(data) == 10485760 or (data and data[-1:] != b'}'):
            chunks = [data]
            while True:
                try:
                    chunk = await asyncio.wait_for(reader.read(65536), timeout=1.0)
                    if not chunk:
                        break
                    chunks.append(chunk)
                except asyncio.TimeoutError:
                    break
            data = b"".join(chunks)
        if not data:
            writer.close()
            await writer.wait_closed()
            return

        message = data.decode()

        try:
            payload = json.loads(message)
            msg_type = payload.get("type")

            if msg_type == "HANDSHAKE":
                new_peer = payload.get("data")
                if str(self.port) not in new_peer:
                    if new_peer not in self.peers:
                        self.peers.add(new_peer)
                        print(f"[Red] 🤝 Peer enlazado: {new_peer}")

                    # Devolver saludo
                    response = json.dumps(
                        {"type": "HANDSHAKE", "data": f"{self.host_public}:{self.port}"}
                    ).encode()
                    writer.write(response)
                    await writer.drain()

            elif msg_type == "REQUEST_CHAIN_SYNC":
                # Un nodo recién conectado pide bloques
                requester_index = payload.get("last_index")
                requester_addr = payload.get("requester")

                local_height = self.blockchain.chain[-1].index

                if local_height > requester_index:
                    print(
                        f"[Red] Nodo {requester_addr} desactualizado. Enviando segmento (Desde {requester_index + 1} a {local_height})..."
                    )

                    # Extraer bloques faltantes
                    blocks_to_send = self.blockchain.chain[
                        requester_index + 1 : requester_index + 51
                    ]  # Paginación: máx 50 bloques
                    blocks_data = [
                        b.to_dict() if hasattr(b, "to_dict") else vars(b)
                        for b in blocks_to_send
                    ]

                    resp_msg = json.dumps(
                        {"type": "CHAIN_SEGMENT", "blocks": blocks_data}
                    ).encode()

                    # Conectar directamente al solicitante para no saturar la red (Gossip)
                    host, port = requester_addr.split(":")
                    try:
                        resp_reader, resp_writer = await asyncio.open_connection(
                            host, int(port)
                        )
                        resp_writer.write(resp_msg)
                        await resp_writer.drain()
                        resp_writer.close()
                        await resp_writer.wait_closed()
                    except Exception as e:
                        print(f"[Red] Error enviando segmento a {requester_addr}: {e}")

            elif msg_type == "CHAIN_SEGMENT":
                print(f"[Debug] Procesando CHAIN_SEGMENT")
                # Recibimos una carga de bloques para ponernos al día
                blocks_data = payload.get("blocks", [])
                if not blocks_data:
                    return

                print(
                    f"[Red] 📥 Descargando segmento de cadena ({len(blocks_data)} bloques recibidos)..."
                )

                added_count = 0
                for b_data in blocks_data:
                    # Deserializar transacciones
                    txs = []
                    for tx_data in b_data["transactions"]:
                        tx = Transaction(
                            sender_m3=tx_data["sender_m3"],
                            receiver_m3=tx_data["receiver_m3"],
                            amount=tx_data["amount"],
                            fee=tx_data.get("fee", 0),
                            signature_data=tx_data.get("signature_data", {}),
                            payload=tx_data.get("payload", {}),
                        )
                        tx.tx_id = tx_data["tx_id"]
                        txs.append(tx)

                    # Construir bloque
                    new_block = Block(
                        index=b_data["index"],
                        transactions=txs,
                        previous_hash=b_data["previous_hash"],
                        timestamp=b_data["timestamp"],
                    )
                    new_block.hash = b_data["hash"]

                    # Intentar inyectar en la base de datos local
                    if self.blockchain.add_block(new_block):
                        added_count += 1
                        self.mempool.remove_mined_transactions(txs)
                    else:
                        print(
                            f"[Red] ⚠️ Segmento abortado en índice {new_block.index}. Conflicto de estado."
                        )
                        break  # Si falla un bloque, descartar el resto del segmento

                print(
                    f"[Red] ✓ Sincronización completada. {added_count} bloques integrados."
                )

            elif msg_type == "NEW_TX":
                tx_data = payload.get("data")
                tx = Transaction(
                    sender_m3=tx_data["sender_m3"],
                    receiver_m3=tx_data["receiver_m3"],
                    amount=tx_data["amount"],
                    fee=tx_data.get("fee", 0),
                    signature_data=tx_data["signature_data"],
                    payload=tx_data.get("payload", {}),
                )
                tx.tx_id = tx_data["tx_id"]
                if self.mempool.add_transaction(tx):
                    print(f"[Red] 📥 TX {tx.tx_id[:8]} recibida vía P2P.")
                    await self.broadcast_transaction(tx)

            elif msg_type == "NEW_BLOCK":
                block_data = payload.get("data")
                if self.syncing:
                    return

                print(f"[Red] 📦 Bloque {block_data['index']} propuesto por la red.")

                txs = []
                for tx_data in block_data["transactions"]:
                    tx = Transaction(
                        sender_m3=tx_data["sender_m3"],
                        receiver_m3=tx_data["receiver_m3"],
                        amount=tx_data["amount"],
                        fee=tx_data.get("fee", 0),
                        signature_data=tx_data.get("signature_data", {}),
                        payload=tx_data.get("payload", {}),
                    )
                    tx.tx_id = tx_data["tx_id"]
                    txs.append(tx)

                new_block = Block(
                    index=block_data["index"],
                    transactions=txs,
                    previous_hash=block_data["previous_hash"],
                    timestamp=block_data["timestamp"],
                )
                new_block.hash = block_data["hash"]

                if self.blockchain.add_block(new_block):
                    print(
                        f"[Red] ✓ Bloque {new_block.index} validado e integrado al ledger local."
                    )
                    self.mempool.remove_mined_transactions(txs)
                else:
                    # FASE F2: Lógica de Detección de Bifurcaciones
                    if new_block.index > self.blockchain.chain[-1].index + 1:
                        print(
                            f"[Red] ❌ Brecha de índice detectada ({new_block.index}). Solicitando sincronización..."
                        )
                        await self.request_sync()
                    else:
                        print(
                            f"[Red] ⚠️ Conflicto de bifurcación detectado en el bloque {new_block.index}."
                        )
                        # Enviar petición al nodo que originó la discrepancia
                        req_msg = json.dumps(
                            {
                                "type": "REQUEST_FULL_CHAIN",
                                "requester": f"{self.host_public}:{self.port}",
                            }
                        ).encode()
                        await self._broadcast(req_msg)

            # --- FASE F2: ENVIAR HISTORIAL COMPLETO ANTE UN CONFLICTO ---
            elif msg_type == "REQUEST_FULL_CHAIN":
                requester_addr = payload.get("requester")
                print(
                    f"[Red] Nodo {requester_addr} solicita resolución de fork. Enviando cadena completa..."
                )
                blocks_data = [
                    b.to_dict() if hasattr(b, "to_dict") else vars(b)
                    for b in self.blockchain.chain
                ]
                resp_msg = json.dumps(
                    {"type": "FULL_CHAIN", "blocks": blocks_data}
                ).encode()

                host, port = requester_addr.split(":")
                try:
                    resp_reader, resp_writer = await asyncio.wait_for(
                        asyncio.open_connection(host, int(port)), timeout=5.0
                    )
                    resp_writer.write(resp_msg)
                    await resp_writer.drain()
                    resp_writer.close()
                    await resp_writer.wait_closed()
                except Exception:
                    pass

            # --- FASE F2: RECIBIR Y EVALUAR HISTORIAL COMPETITIVO ---
            elif msg_type == "FULL_CHAIN":
                blocks_data = payload.get("blocks", [])
                if len(blocks_data) <= len(self.blockchain.chain):
                    return  # Ignorar silenciosamente si la cadena recibida es inferior o igual

                print(
                    f"[Red] 📥 Descargando historial competitivo ({len(blocks_data)} bloques)..."
                )
                new_chain = []
                for b_data in blocks_data:
                    txs = []
                    for tx_data in b_data["transactions"]:
                        tx = Transaction(
                            sender_m3=tx_data["sender_m3"],
                            receiver_m3=tx_data["receiver_m3"],
                            amount=tx_data["amount"],
                            signature_data=tx_data.get("signature_data", {}),
                            payload=tx_data.get("payload", {}),
                        )
                        tx.tx_id = tx_data["tx_id"]
                        txs.append(tx)

                    new_b = Block(
                        index=b_data["index"],
                        transactions=txs,
                        previous_hash=b_data["previous_hash"],
                        timestamp=b_data["timestamp"],
                    )
                    new_b.hash = b_data["hash"]
                    new_chain.append(new_b)

                if self.blockchain.replace_chain(new_chain):
                    for b in new_chain:
                        self.mempool.remove_mined_transactions(b.transactions)

        except json.JSONDecodeError:
            pass
        except Exception as e:
            print(f"[Red] Error procesando mensaje: {e}")

        writer.close()
        await writer.wait_closed()

    async def broadcast_transaction(self, tx: Transaction):
        message = json.dumps({"type": "NEW_TX", "data": tx.to_dict()}).encode()
        await self._broadcast(message)

    async def broadcast_block(self, block: Block):
        tx_list = [
            tx.to_dict() if hasattr(tx, "to_dict") else tx for tx in block.transactions
        ]
        message = json.dumps(
            {
                "type": "NEW_BLOCK",
                "data": {
                    "index": block.index,
                    "hash": block.hash,
                    "previous_hash": block.previous_hash,
                    "timestamp": block.timestamp,
                    "transactions": tx_list,
                },
            }
        ).encode()
        await self._broadcast(message)

    async def _broadcast(self, message: bytes):
        for peer in list(self.peers):
            if peer in self.banned_peers:
                continue

            host, port = peer.split(":")
            try:
                # TIMEOUT ESTRICTO: 3 segundos máximo por conexión
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, int(port)), timeout=3.0
                )
                writer.write(message)
                await writer.drain()
                try:
                    response = await asyncio.wait_for(reader.read(4096), timeout=2.0)
                    if response:
                        import json as _json
                        resp = _json.loads(response.decode())
                        if resp.get("type") == "HANDSHAKE":
                            new_peer = resp.get("data")
                            if new_peer and str(self.port) not in new_peer:
                                if new_peer not in self.peers:
                                    self.peers.add(new_peer)
                                print(f"[Red] 🤝 Peer enlazado: {new_peer}")
                except Exception:
                    pass
                writer.close()
                await writer.wait_closed()

                # Si tuvo éxito, reseteamos sus fallos
                self.peer_failures[peer] = 0

            except asyncio.TimeoutError:
                print(f"[Red P2P] Timeout conectando a {peer}")
                self.penalize_peer(peer)
            except Exception as e:
                self.penalize_peer(peer)


class P2PNetwork:
    def __init__(self):
        self.peers = set()
        self.banned_peers = set()
        self.max_failures = 3
        self.peer_failures = {}

    def penalize_peer(self, peer: str):
        """Aísla nodos caídos o que envían respuestas inválidas."""
        self.peer_failures[peer] = self.peer_failures.get(peer, 0) + 1
        if self.peer_failures[peer] >= self.max_failures:
            print(f"[P2P] Nodo inalcanzable o malicioso. Expulsando: {peer}")
            if peer in self.peers:
                self.peers.remove(peer)
            self.banned_peers.add(peer)

    def request_chain_sync(self, peer: str):
        """Ejemplo de petición de lectura con timeout y captura de errores."""
        if peer in self.banned_peers:
            return None

        try:
            # Timeout estricto de 5 segundos para evitar bloqueos del hilo principal
            response = requests.get(f"{peer}/blocks", timeout=5.0)

            if response.status_code == 200:
                self.peer_failures[peer] = (
                    0  # Reiniciar contador de fallos si responde bien
                )
                return response.json()
            else:
                self.penalize_peer(peer)
                return None

        except requests.exceptions.RequestException:
            self.penalize_peer(peer)
            return None

    def broadcast_block(self, block_data: dict):
        """Difusión no bloqueante a todos los pares activos."""

        def _send_to_peer(peer, data):
            try:
                # Timeout agresivo de 3 segundos para escrituras
                requests.post(f"{peer}/block/new", json=data, timeout=3.0)
            except requests.exceptions.RequestException:
                self.penalize_peer(peer)

        for peer in list(self.peers):
            if peer not in self.banned_peers:
                # Desacoplar la petición de red en un hilo secundario
                thread = threading.Thread(
                    target=_send_to_peer, args=(peer, block_data), daemon=True
                )
                thread.start()
