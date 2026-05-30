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
import hashlib
import time
import json

import requests
from blockchain.block import Block, Transaction
from blockchain.chain import Blockchain

from network.mempool import Mempool


class CAFNode:
    def __init__(self, host: str, port: int, blockchain: Blockchain, mempool: Mempool, host_public: str = None, geo_identity: dict = None):
        self.host = host
        self.port = port
        self.host_public = host_public or host
        self.blockchain = blockchain
        self.mempool = mempool
        self.peers = set()
        self.authenticated_peers: dict = {}  # peer → {m3_hash, m3, authenticated_at}
        self.observer_peers: set = set()
        self.syncing = False
        self.sync_target = 0
        # --- Control de resiliencia P2P ---
        self.banned_peers = set()
        self.peer_failures = {}
        self.max_failures = 8  # más tolerante — red intermitente
        # Peers permanentes — nunca se eliminan aunque fallen
        # permanent_peers se construye dinámicamente desde el FVR
        self._static_peers = {
            "157.180.113.24:65432",
            "157.180.113.24:65433",
        }
        # --- Identidad geométrica ---
        self.geo_identity = geo_identity
        self.geo_proof = None
        self.geo_nonce = None
        self.geo_proof_expiry = 0

    @property
    def permanent_peers(self):
        """Peers permanentes = endpoints del FVR + peers estáticos."""
        fvr_peers = set()
        try:
            for v in self.blockchain.validator_registry.validators.values():
                ep = v.get("endpoint", "")
                if ep and not v.get("slashed"):
                    fvr_peers.add(ep)
        except Exception:
            pass
        return fvr_peers | self._static_peers


    def penalize_peer(self, peer: str):
        """Aísla nodos caídos o que envían respuestas inválidas."""
        self.peer_failures[peer] = self.peer_failures.get(peer, 0) + 1
        if self.peer_failures[peer] >= self.max_failures:
            if peer in self.permanent_peers:
                # Peers permanentes nunca se banean — solo se marcan para retry
                print(f"[Red P2P] Peer permanente inalcanzable: {peer} — reintentando en maintenance")
                self.peer_failures[peer] = 0  # reset para seguir intentando
                return
            print(f"[Red P2P] Nodo inalcanzable. Expulsando: {peer}")
            if peer in self.peers:
                self.peers.remove(peer)
            self.banned_peers.add(peer)


    async def _compute_geo_proof(self):
        """Precomputa el ZK proof para GEO_HANDSHAKE. Válido 1 hora."""
        if not self.geo_identity or not self.geo_identity.get("private_key"):
            return
        try:
            from crypto.zkp import ZKEngine
            from core.verifier import CriterionParams
            nonce = hashlib.sha256(
                f"{self.host_public}:{self.port}:{int(time.time()//3600)}".encode()
            ).hexdigest()
            priv = self.geo_identity["private_key"]
            pub  = self.geo_identity["public_m3"]
            att  = self.geo_identity["attractor"]
            params = self.geo_identity["criterion_params"]
            if isinstance(params, dict):
                params = CriterionParams(**params)
            proof = ZKEngine.generate_proof(priv, pub, nonce, params, att)
            self.geo_proof = proof
            self.geo_nonce = nonce
            self.geo_proof_expiry = time.time() + 3600
            print(f"[GEO] Proof precomputado. Válido 1h.")
        except Exception as e:
            print(f"[GEO] Error computando proof: {e}")

    def _build_geo_handshake(self) -> bytes:
        """Construye el mensaje GEO_HANDSHAKE o HANDSHAKE simple."""
        endpoint = f"{self.host_public}:{self.port}"
        if self.geo_proof and time.time() < self.geo_proof_expiry:
            import json as _j
            m3_hash = hashlib.sha256(
                _j.dumps(self.geo_identity["public_m3"], sort_keys=True, separators=(",",":")).encode()
            ).hexdigest()
            return json.dumps({
                "type": "GEO_HANDSHAKE",
                "endpoint": endpoint,
                "m3": self.geo_identity["public_m3"],
                "m3_hash": m3_hash,
                "zk_proof": self.geo_proof,
                "nonce": self.geo_nonce,
            }).encode()
        return json.dumps({"type": "HANDSHAKE", "data": endpoint}).encode()

    def _verify_geo_handshake(self, payload: dict) -> bool:
        """Verifica un GEO_HANDSHAKE entrante."""
        try:
            from crypto.zkp import ZKEngine
            from core.verifier import CriterionParams
            m3 = payload.get("m3")
            nonce = payload.get("nonce")
            proof = payload.get("zk_proof")
            if not m3 or not nonce or not proof:
                return False
            # Nonce reciente (< 2 horas)
            # El nonce es sha256(endpoint:hora) — no podemos verificar timestamp directamente
            # pero el ZK proof lo vincula al nonce
            params_raw = proof.get("criterion_params")
            if not params_raw:
                return False
            params = CriterionParams(**params_raw) if isinstance(params_raw, dict) else params_raw
            return ZKEngine.verify_proof(proof, m3, nonce, params)
        except Exception as e:
            print(f"[GEO] Error verificando proof: {e}")
            return False

    async def start_server(self):
        server = await asyncio.start_server(self.handle_client, self.host, self.port)
        addr = server.sockets[0].getsockname()
        print(f"[Red] Nodo P2P escuchando en {addr[0]}:{addr[1]}")

        # Iniciar descubrimiento y sincronización al levantar el nodo
        asyncio.create_task(self._compute_geo_proof())
        asyncio.create_task(self.announce_to_peers())
        asyncio.create_task(self.peer_maintenance_loop())

        async with server:
            await server.serve_forever()

    async def announce_to_peers(self):
        """Envía un handshake inicial a los pares y solicita sincronización."""
        await asyncio.sleep(1)
        if self.peers:
            # 1. Informar existencia (GEO_HANDSHAKE si tenemos identidad)
            handshake = self._build_geo_handshake()
            await self._broadcast(handshake)

            # 2. Compartir lista de peers (full mesh discovery)
            await self._broadcast_peer_list()

            # 3. FASE F1: Solicitar sincronización del historial
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

        # Mantener syncing=True hasta estar al día
        # Verificar cada 3s si la cadena sigue creciendo
        prev_height = self.blockchain.chain[-1].index
        for _ in range(40):  # máx 120s
            await asyncio.sleep(3)
            curr_height = self.blockchain.chain[-1].index
            if curr_height == prev_height:
                break  # dejó de crecer — sincronización completa
            prev_height = curr_height
        self.syncing = False
        print(f"[Red] ✓ Sincronización completa. Altura: {self.blockchain.chain[-1].index}")

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

        try:
            message = data.decode("utf-8")
        except UnicodeDecodeError:
            print(f"[P2P] Datos binarios inválidos recibidos — ignorando")
            writer.close()
            return

        try:
            payload = json.loads(message)
            msg_type = payload.get("type")

            if msg_type == "GEO_HANDSHAKE":
                new_peer = payload.get("endpoint")
                if new_peer and str(self.port) not in new_peer:
                    if self._verify_geo_handshake(payload):
                        m3_hash = payload.get("m3_hash")
                        self.authenticated_peers[new_peer] = {
                            "m3_hash": m3_hash,
                            "m3": payload.get("m3"),
                            "authenticated_at": time.time(),
                        }
                        if new_peer not in self.peers:
                            self.peers.add(new_peer)
                        is_validator = self.blockchain.validator_registry.validators.get(m3_hash)
                        role = "validador" if is_validator else "nodo autenticado"
                        print(f"[GEO] Peer autenticado ({role}): {new_peer}")
                    else:
                        if new_peer not in self.peers:
                            self.peers.add(new_peer)
                            self.observer_peers.add(new_peer)
                            print(f"[Red] Observer enlazado: {new_peer}")
                    response = self._build_geo_handshake()
                    writer.write(response)
                    await writer.drain()

            elif msg_type == "HANDSHAKE":
                new_peer = payload.get("data")
                if new_peer and str(self.port) not in new_peer:
                    if new_peer not in self.peers:
                        self.peers.add(new_peer)
                        self.observer_peers.add(new_peer)
                        print(f"[Red] Peer enlazado (observer): {new_peer}")
                    response = self._build_geo_handshake()
                    writer.write(response)
                    await writer.drain()

            elif msg_type == "PEER_LIST":
                received_peers = payload.get("peers", [])
                my_addr = f"{self.host_public}:{self.port}"
                new_peers = [
                    p for p in received_peers
                    if p != my_addr
                    and p not in self.peers
                    and p not in self.banned_peers
                    and str(self.port) not in p
                ]
                for p in new_peers:
                    self.peers.add(p)
                    print(f"[Red] 🌐 Peer descubierto via malla: {p}")
                if new_peers:
                    handshake = self._build_geo_handshake()
                    for p in new_peers:
                        asyncio.create_task(self._send_to_peer(p, handshake))
                    await self._broadcast_peer_list()

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

                    peer_height = len(self.blockchain.chain) - 1
                    resp_msg = json.dumps(
                        {"type": "CHAIN_SEGMENT", "blocks": blocks_data, "peer_height": peer_height}
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

                # Recibimos una carga de bloques para ponernos al día
                blocks_data = payload.get("blocks", [])
                if not blocks_data:
                    return

                print(
                    f"[Red] 📥 Descargando segmento de cadena ({len(blocks_data)} bloques recibidos)..."
                )

                peer_height = payload.get("peer_height", 0)
                if peer_height > 0:
                    self.sync_target = peer_height
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
                    if self.blockchain.add_block(new_block, skip_zk=True):
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

                # Si el segmento fue completo (50), hay más bloques — solicitar el siguiente
                local_height = self.blockchain.chain[-1].index
                if self.sync_target > 0 and local_height < self.sync_target - 2:
                    print(f'[Red] Segmento completo — solicitando siguiente desde {local_height}... (target={self.sync_target})')
                    req_msg = json.dumps({
                        "type": "REQUEST_CHAIN_SYNC",
                        "last_index": local_height,
                        "requester": f"{self.host_public}:{self.port}",
                    }).encode()
                    await self._broadcast(req_msg)
                else:
                    self.sync_target = 0
                    self.syncing = False
                    print(f'[Red] ✓ Sincronización completa. Altura: {local_height}')

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
                loop = asyncio.get_event_loop()
                success = await loop.run_in_executor(None, self.mempool.add_transaction, tx)
                if success:
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
                        # Esperar más tiempo antes de sync — puede ser condición de carrera
                        await asyncio.sleep(5)
                        # Verificar si ya se resolvió solo
                        current = self.blockchain.chain[-1].index
                        if new_block.index > current + 1:
                            print(
                                f"[Red] ❌ Brecha de índice detectada ({new_block.index}). Solicitando sincronización..."
                            )
                            await self.request_sync()
                        # Si ya se resolvió, no hacer nada
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

            elif msg_type == "STATUS_REQUEST":
                import time
                last_block = self.blockchain.chain[-1]
                status = {
                    "type": "STATUS_RESPONSE",
                    "height": last_block.index,
                    "latest_hash": last_block.hash,
                    "latest_ts": last_block.timestamp,
                    "peers": list(self.peers),
                    "syncing": self.syncing,
                    "now": time.time()
                }
                writer.write(json.dumps(status).encode())
                await writer.drain()
                return
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

    async def _broadcast_peer_list(self):
        """Comparte lista completa de peers para construir la malla."""
        if not self.peers:
            return
        peer_list_msg = json.dumps({
            "type": "PEER_LIST",
            "peers": list(self.peers) + [f"{self.host_public}:{self.port}"]
        }).encode()
        await self._broadcast(peer_list_msg)

    async def _send_to_peer(self, peer: str, message: bytes):
        """Envía un mensaje a un peer específico."""
        host, port = peer.split(":")
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, int(port)), timeout=3.0
            )
            writer.write(message)
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            self.peer_failures[peer] = 0
        except Exception:
            self.penalize_peer(peer)

    async def peer_maintenance_loop(self):
        """Cada 30s: reconecta peers offline, refresca malla, reintenta permanentes."""
        await asyncio.sleep(15)
        while True:
            try:
                await asyncio.sleep(30)
                my_addr = f"{self.host_public}:{self.port}"

                # Rehabilitar peers baneados
                for peer in list(self.banned_peers):
                    if peer == my_addr: continue
                    host, port = peer.split(":")
                    try:
                        reader, writer = await asyncio.wait_for(
                            asyncio.open_connection(host, int(port)), timeout=3.0
                        )
                        writer.close()
                        await writer.wait_closed()
                        self.banned_peers.discard(peer)
                        self.peer_failures[peer] = 0
                        self.peers.add(peer)
                        print(f"[Red] ♻️  Peer rehabilitado: {peer}")
                        handshake = self._build_geo_handshake()
                        asyncio.create_task(self._send_to_peer(peer, handshake))
                    except Exception:
                        pass

                # Reintentar peers permanentes perdidos — malla siempre completa
                for peer in self.permanent_peers:
                    if peer == my_addr: continue
                    if peer in self.peers: continue
                    host, port = peer.split(":")
                    try:
                        reader, writer = await asyncio.wait_for(
                            asyncio.open_connection(host, int(port)), timeout=3.0
                        )
                        writer.close()
                        await writer.wait_closed()
                        self.banned_peers.discard(peer)
                        self.peer_failures[peer] = 0
                        self.peers.add(peer)
                        print(f"[Red] 🔗 Peer permanente reconectado: {peer}")
                        handshake = self._build_geo_handshake()
                        asyncio.create_task(self._send_to_peer(peer, handshake))
                    except Exception:
                        pass

                # Refrescar malla
                if self.peers:
                    await self._broadcast_peer_list()
                active = len(self.peers)
                missing = [p for p in self.permanent_peers if p not in self.peers and p != my_addr]
                if missing:
                    print(f"[Red] 🔄 Mantenimiento: {active} activos — offline: {', '.join(missing)}")
                else:
                    print(f"[Red] 🔄 Mantenimiento: {active} peers — malla completa ✓")
            except Exception as e:
                print(f"[Red] ⚠️  Error en maintenance loop: {e}")
                await asyncio.sleep(5)

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
