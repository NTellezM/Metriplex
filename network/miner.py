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

        # Esperar conexión a peers antes de cualquier cosa
        for _ in range(30):
            await asyncio.sleep(1)
            if self.p2p_node.peers:
                break

        # Verificar que nuestro último bloque coincide con el de los peers
        if self.p2p_node.peers:
            local_hash = self.blockchain.chain[-1].hash
            local_idx  = self.blockchain.chain[-1].index
            for peer in list(self.p2p_node.peers)[:2]:
                try:
                    host, port = peer.rsplit(":", 1)
                    r = requests.get(f"http://{host}:{int(port)-57432}/info", timeout=3)
                    peer_info = r.json()
                    peer_hash = peer_info.get("latest_block_hash", "")
                    peer_len  = peer_info.get("chain_length", 0)
                    if peer_len > local_idx and peer_hash != local_hash:
                        print(f"[Consenso] Chain local diverge de {peer} — resincronizando DB...")
                        # Borrar último bloque conflictivo
                        self.blockchain.storage.conn.execute(
                            "DELETE FROM blocks WHERE block_index = ?", (local_idx,)
                        )
                        self.blockchain.storage.conn.commit()
                        self.blockchain.chain.pop()
                        await self.p2p_node.request_sync()
                        # Esperar sync
                        for _ in range(120):
                            await asyncio.sleep(1)
                            if getattr(self.p2p_node, 'sync_target', 0) == 0:
                                break
                        break
                except Exception:
                    pass
        # Espera final — no minar hasta sync completo
        for _ in range(120):
            await asyncio.sleep(1)
            syncing = getattr(self.p2p_node, "sync_target", 0) > 0
            if not syncing and len(self.blockchain.chain) > 1:
                break
        print(f"[Consenso] Sync completado. Altura: {len(self.blockchain.chain)-1}. Iniciando minero.")

        async def _check_synced_with_peers() -> bool:
            local_h = len(self.blockchain.chain)
            sync_target = getattr(self.p2p_node, 'sync_target', 0)
            if sync_target > 0 and local_h < sync_target - 2:
                print(f"[Consenso] Esperando sync: local={local_h} target={sync_target} lag={sync_target-local_h}")
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
                    self.p2p_node.sync_target = 0  # reset — evita bloqueo permanente
                    await asyncio.sleep(1)
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
                await asyncio.sleep(10)
                # Si otro nodo ya minó este slot durante la espera, ceder
                if current_slot == self.last_mined_slot or len(self.blockchain.chain) > last_block.index + 1:
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
