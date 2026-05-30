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
Módulo de consenso para el protocolo CAF.
Implementa Elección de Líder Pseudoaleatoria Verificable basada en Slots de tiempo.
"""

import asyncio
import hashlib
import time

from blockchain.block import Block, Transaction
from blockchain.chain import Blockchain
from core.arithmetic import SCALE_FACTOR

from network.mempool import Mempool
import json
import requests
from blockchain.validator_registry import LAMBDA_MIN, LAMBDA_MAX


class AutoMiner:
    BLOCK_REWARD = 50 * SCALE_FACTOR  # Recompensa inicial por bloque
    HALVING_INTERVAL = 210_000          # Bloques entre cada halving (como Bitcoin)

    def __init__(
        self,
        blockchain: Blockchain,
        mempool: Mempool,
        p2p_node,
        block_time_seconds: int = 10,
        miner_m3: list = None,  # Tensor M3 de la billetera del minero
    ):
        self.blockchain = blockchain
        self.mempool = mempool
        self.p2p_node = p2p_node
        self.block_time_seconds = block_time_seconds
        self.last_mined_slot = 0
        self.miner_m3 = miner_m3  # None = sin recompensa automática

    async def start(self):
        my_address = f"127.0.0.1:{self.p2p_node.port}"
        print(
            f"[Consenso] Motor de Elección de Líder iniciado. Identidad: {my_address}"
        )
        # ── ARRANQUE SEGURO ─────────────────────────────────────────────
        # Regla: el nodo con más bloques es la fuente de verdad.
        # Nunca minar si hay un peer con altura mayor.
        # ────────────────────────────────────────────────────────────────
        BOOTSTRAP_TIMEOUT = 300  # 5 min esperando peers

        # FASE 1 — Esperar al menos 1 peer activo
        print("[Consenso] Esperando peers antes de iniciar minero...")
        waited = 0
        while not self.p2p_node.peers and waited < BOOTSTRAP_TIMEOUT:
            await asyncio.sleep(2)
            waited += 2
            if waited % 30 == 0:
                print(f"[Consenso] Sin peers tras {waited}s — reintentando bootstrap...")
                for bp in self.p2p_node.permanent_peers:
                    if bp not in self.p2p_node.peers:
                        self.p2p_node.peers.add(bp)
                asyncio.create_task(self.p2p_node.announce_to_peers())

        if not self.p2p_node.peers:
            print("[Consenso] Sin peers tras 5min — arrancando como nodo solitario.")
        else:
            print(f"[Consenso] {len(self.p2p_node.peers)} peers encontrados.")
            # Esperar handshake P2P completo antes de consultar HTTP
            await asyncio.sleep(8)

        # FASE 2 — Consultar altura de peers con reintentos
        local_idx  = self.blockchain.chain[-1].index
        local_hash = self.blockchain.chain[-1].hash
        max_peer_h = 0
        best_peer  = None
        best_peer_hash = None
        import httpx as _hx

        for attempt in range(3):
            for peer in list(self.p2p_node.peers)[:4]:
                try:
                    host, port = peer.rsplit(":", 1)
                    async with _hx.AsyncClient(timeout=5.0) as _c:
                        r = await _c.get(f"http://{host}:{int(port)-57432}/info")
                    peer_info = r.json()
                    ph = peer_info.get("chain_length", 0)
                    if ph > max_peer_h:
                        max_peer_h = ph
                        best_peer  = peer
                        best_peer_hash = peer_info.get("latest_block_hash", "")
                except Exception:
                    pass
            if max_peer_h > 0:
                break
            if attempt < 2:
                print(f"[Consenso] Peers sin respuesta HTTP — reintentando ({attempt+1}/3)...")
                await asyncio.sleep(5)

        need_sync = False
        if max_peer_h == 0:
            # Ningún peer respondió HTTP — esperar más antes de minar
            print(f"[Consenso] Peers sin respuesta — esperando 30s antes de minar solo...")
            await asyncio.sleep(30)
            # Reintentar una vez más
            for peer in list(self.p2p_node.peers)[:4]:
                try:
                    host, port = peer.rsplit(":", 1)
                    async with _hx.AsyncClient(timeout=5.0) as _c:
                        r = await _c.get(f"http://{host}:{int(port)-57432}/info")
                    peer_info = r.json()
                    ph = peer_info.get("chain_length", 0)
                    if ph > max_peer_h:
                        max_peer_h = ph
                        best_peer  = peer
                        best_peer_hash = peer_info.get("latest_block_hash", "")
                except Exception:
                    pass
            if max_peer_h == 0:
                print(f"[Consenso] Sin respuesta tras espera — arrancando como nodo solitario ({local_idx}).")
        if max_peer_h > local_idx:
            print(f"[Consenso] Peer {best_peer} tiene altura {max_peer_h} > local {local_idx} — sincronizando...")
            need_sync = True
        elif max_peer_h == local_idx and best_peer_hash and best_peer_hash != local_hash:
            print(f"[Consenso] Misma altura pero hash distinto — fork detectado, sincronizando...")
            need_sync = True
        elif max_peer_h > 0:
            print(f"[Consenso] Cadena local sincronizada ({local_idx}). Listo para minar.")
        else:
            print(f"[Consenso] Nodo solitario ({local_idx}). Iniciando minero.")

        if need_sync:
            await self.p2p_node.request_sync()
            prev_h = local_idx
            stalled = 0
            while True:
                await asyncio.sleep(3)
                curr_h = self.blockchain.chain[-1].index
                if curr_h >= max_peer_h - 1:
                    print(f"[Consenso] Sincronizado. Altura: {curr_h}")
                    break
                if curr_h == prev_h:
                    stalled += 1
                    if stalled > 20:
                        print(f"[Consenso] Sync estancado en {curr_h} — reintentando...")
                        await self.p2p_node.request_sync()
                        stalled = 0
                else:
                    stalled = 0
                prev_h = curr_h

        print(f"[Consenso] Arranque completo. Altura: {self.blockchain.chain[-1].index}. Iniciando minero.")
        print(f"[Consenso] Sync completado. Altura: {len(self.blockchain.chain)-1}. Iniciando minero.")

        async def _check_synced_with_peers() -> bool:
            local_h    = len(self.blockchain.chain)
            local_hash = self.blockchain.chain[-1].hash if self.blockchain.chain else None
            sync_target = getattr(self.p2p_node, 'sync_target', 0)

            # Guardia 1 — sync_target explícito
            if sync_target > 0 and local_h < sync_target - 2:
                print(f"[Consenso] Esperando sync: local={local_h} target={sync_target}")
                return False

            # Sin peers — nodo solitario, puede minar
            if not self.p2p_node.peers:
                return True

            # Guardia 2 — consultar altura Y hash de peers activos
            peer_heights = []
            peer_hashes  = {}
            for peer in list(self.p2p_node.peers)[:3]:
                try:
                    host, port = peer.rsplit(":", 1)
                    api_port   = int(port) - 57432
                    async with __import__('httpx').AsyncClient(timeout=3.0) as _c:
                        r = await _c.get(f"http://{host}:{api_port}/info")
                    data = r.json()
                    ph = data.get("chain_length", 0)
                    hh = data.get("latest_block_hash", "")
                    if ph > 0:
                        peer_heights.append(ph)
                        peer_hashes[peer] = (ph, hh)
                except:
                    pass

            if not peer_heights:
                return True  # peers no responden — no bloquear

            max_peer_h = max(peer_heights)

            # Altura muy atrasada — esperar sync
            if local_h < max_peer_h - 2:
                print(f"[Consenso] Lag detectado: local={local_h} peers_max={max_peer_h} — esperando sync")
                return False

            # Verificar hash — si mi hash no coincide con el de peers en mi altura → fork
            for peer, (ph, hh) in peer_hashes.items():
                if ph == local_h and hh and local_hash and hh != local_hash:
                    print(f"[Consenso] Hash mismatch con {peer}: local={local_hash[:8]} peer={hh[:8]} — intentando restore desde backup")
                    # Intentar restore desde backup más reciente
                    import glob, shutil, os
                    db_path  = self.blockchain.storage.db_path
                    backup_dir = os.path.join(os.path.dirname(db_path), 'backups')
                    backups  = sorted(glob.glob(os.path.join(backup_dir, '*.db')), reverse=True)
                    restored = False
                    for backup in backups[:3]:  # intentar los 3 más recientes
                        try:
                            count = int(__import__('sqlite3').connect(backup).execute(
                                "SELECT count(*) FROM blocks").fetchone()[0])
                            if count >= max_peer_h - 10:
                                shutil.copy2(backup, db_path)
                                print(f"[Consenso] Restore desde {os.path.basename(backup)} ({count} bloques)")
                                restored = True
                                break
                        except:
                            continue
                    if not restored:
                        print(f"[Consenso] No se encontró backup válido — esperando replace_chain por p2p")
                    return False

            return True

        while True:
            await asyncio.sleep(1)  # Evaluar el estado de la red cada segundo

            # 1. Definición del Slot de Tiempo Universal
            current_time = time.time()
            current_slot = int(current_time // self.block_time_seconds)

            # Esperar sincronización completa antes de minar
            # Sin peers: solo bloquear si no somos validador FVR registrado
            if not self.p2p_node.peers:
                registry = self.blockchain.validator_registry
                my_hash = hashlib.sha256(
                    json.dumps(self.miner_m3, sort_keys=True, separators=(",",":")).encode()
                ).hexdigest() if self.miner_m3 else None
                if not my_hash or not registry.validators.get(my_hash):
                    await asyncio.sleep(1)
                    continue
                # Es validador FVR — puede minar solo
            if self.p2p_node.sync_target > 0:
                local_h = len(self.blockchain.chain) - 1
                if local_h < self.p2p_node.sync_target - 2:
                    await asyncio.sleep(5)
                    continue
            # Guardia 2 — altura vs peers
            if not await _check_synced_with_peers():
                await asyncio.sleep(5)
                continue
            # Evitar minar múltiples veces en la misma ventana de tiempo
            if current_slot == self.last_mined_slot:
                continue

            # 2. Validator set — FVR si hay validadores registrados,
            #    fallback a peers+self para compatibilidad Phase 1
            registry = self.blockchain.validator_registry
            fvr_validators = registry.get_sorted_validators()

            # Excluir validadores sin nodo activo (keystore perdido)
            EXCLUDED_VALIDATORS = {"ee481176"}
            fvr_validators = [v for v in fvr_validators if not any(v["m3_hash"].startswith(ex) for ex in EXCLUDED_VALIDATORS)]

            last_block = self.blockchain.chain[-1]
            if fvr_validators:
                EPOCH_SLOTS = 100
                anchor_block = self.blockchain.chain[0]
                for blk in reversed(self.blockchain.chain):
                    if blk.index <= (current_slot // EPOCH_SLOTS) * EPOCH_SLOTS:
                        anchor_block = blk
                        break
                # Lyapunov Consensus
                def _get_lambda(v):
                    if v.get('lambda_value') is not None:
                        return v['lambda_value']
                    h = int(v['m3_hash'], 16) % (2 ** 32)
                    return LAMBDA_MIN + (LAMBDA_MAX - LAMBDA_MIN) * h / (2 ** 32)
                anchor_int = int(hashlib.sha256(
                    f"{anchor_block.hash}{current_slot}".encode()
                ).hexdigest(), 16)
                lambda_E = LAMBDA_MIN + (LAMBDA_MAX - LAMBDA_MIN) * (anchor_int / 2 ** 256)
                leader_m3_hash = min(
                    fvr_validators,
                    key=lambda v: abs(_get_lambda(v) - lambda_E)
                )['m3_hash']
                my_m3_hash = hashlib.sha256(
                    json.dumps(self.miner_m3, sort_keys=True, separators=(',', ':')).encode()
                ).hexdigest() if self.miner_m3 else None
                is_leader = (my_m3_hash == leader_m3_hash)
            else:
                # Phase 1 fallback: peers + self
                validators = sorted(list(self.p2p_node.peers) + [my_address])
                if not validators:
                    is_leader = False
                else:
                    last_block = self.blockchain.chain[-1]
                    seed = f"{last_block.hash}{current_slot}".encode()
                    leader_hash = int(hashlib.sha256(seed).hexdigest(), 16)
                    leader_index = leader_hash % len(validators)
                    is_leader = (my_address == validators[leader_index])

            # 4b. Forjado de Bloque (Solo si este nodo ganó la lotería del slot)
            if is_leader:
                # Ventana de agregación — esperar que lleguen bloques de otros nodos
                await asyncio.sleep(3)
                # Si otro nodo ya minó este slot durante la espera, ceder
                current_tip = self.blockchain.chain[-1]
                if (current_slot == self.last_mined_slot
                        or current_tip.index > last_block.index
                        or current_tip.hash != last_block.hash):
                    continue
                txs = self.mempool.get_transactions_for_block(limit=10)

                self.last_mined_slot = current_slot

                # Recompensa Coinbase para el minero (si tiene billetera configurada)
                if self.miner_m3:
                    coinbase_tx = Transaction(
                        sender_m3=[],
                        receiver_m3=self.miner_m3,
                        amount=self.BLOCK_REWARD,
                        signature_data={"type": "COINBASE"},
                    )
                    txs = [coinbase_tx] + list(txs)

                if txs:

                    new_block = Block(
                        index=last_block.index + 1,
                        transactions=txs,
                        previous_hash=last_block.hash,
                        timestamp=current_time,
                    )

                    success = self.blockchain.add_block(new_block)

                    if success:
                        self.mempool.remove_mined_transactions(txs)
                        print(
                            f"\n[Consenso] 👑 Fui elegido líder (Slot {current_slot}). Bloque {new_block.index} forjado."
                        )
                        await self.p2p_node.broadcast_block(new_block)
