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

        while True:
            await asyncio.sleep(1)  # Evaluar el estado de la red cada segundo

            # 1. Definición del Slot de Tiempo Universal
            current_time = time.time()
            current_slot = int(current_time // self.block_time_seconds)

            # Evitar minar múltiples veces en la misma ventana de tiempo
            if current_slot == self.last_mined_slot:
                continue

            # 2. Validator set — FVR si hay validadores registrados,
            #    fallback a peers+self para compatibilidad Phase 1
            registry = self.blockchain.validator_registry
            fvr_validators = registry.get_sorted_validators()

            last_block = self.blockchain.chain[-1]
            if fvr_validators:
                # FVR: set global determinístico desde genesis
                # Usar bloque anclado al inicio del epoch (cada 10 slots)
                EPOCH_SLOTS = 10
                epoch_start_slot = (current_slot // EPOCH_SLOTS) * EPOCH_SLOTS
                chain_len = len(self.blockchain.chain)
                anchor_idx = max(0, chain_len - EPOCH_SLOTS)
                anchor_block = self.blockchain.chain[anchor_idx]
                seed = f"{anchor_block.hash}{current_slot}".encode()
                leader_hash = int(hashlib.sha256(seed).hexdigest(), 16)
                leader_index = leader_hash % len(fvr_validators)
                leader_m3_hash = fvr_validators[leader_index]["m3_hash"]
                import hashlib as _hlib, json as _json
                my_m3_hash = _hlib.sha256(
                    _json.dumps(self.miner_m3, sort_keys=True, separators=(",",":")).encode()
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
