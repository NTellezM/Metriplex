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
blockchain/chain.py — Libro Mayor Distribuido CAF v2
=====================================================
Correcciones v2:
  - Dead code eliminado de validate_transaction (verificación duplicada post-return)
  - load_chain_from_disk restaura el campo payload en cada Transaction
  - validate_transaction acepta criterion_params embebidos en signature_data
    para usar ZKEngine.verify_proof completo cuando están disponibles
"""

import hashlib
import json

from blockchain.block import Block, Transaction
from blockchain.state import StateDB
from blockchain.storage import Storage


class Blockchain:
    def __init__(self, storage: Storage):
        self.storage = storage
        self.state_db = StateDB(self.storage)
        self.chain = []
        self.unconfirmed_transactions = []
        self.load_chain_from_disk()

    # ── Carga desde disco ──────────────────────────────────────────────────

    def load_chain_from_disk(self):
        """Reconstruye la cadena completa desde la base de datos al iniciar."""
        blocks_data = self.storage.get_all_blocks()
        if not blocks_data:
            self.create_genesis_block()
            return

        for row in blocks_data:
            index, b_hash, prev_hash, timestamp, tx_json = row

            tx_list_raw = json.loads(tx_json)
            transactions = []
            for tx_data in tx_list_raw:
                tx = Transaction(
                    sender_m3=tx_data["sender_m3"],
                    receiver_m3=tx_data["receiver_m3"],
                    amount=tx_data["amount"],
                    fee=tx_data.get("fee", 0),  # <-- BUG CORREGIDO
                    signature_data=tx_data.get("signature_data", {}),
                    payload=tx_data.get("payload", {}),
                )
                tx.tx_id = tx_data["tx_id"]
                transactions.append(tx)

            block = Block(index, transactions, prev_hash, timestamp)
            block.hash = b_hash
            self.chain.append(block)

    # ── Bloque génesis ────────────────────────────────────────────────────

    def get_tensor_hash(self, m3_tensor: list) -> str:
        return self.state_db._hash_tensor(m3_tensor)

    def create_genesis_block(self):
        """Bloque génesis con hash universal fijo — igual en todos los nodos."""
        genesis = Block(index=0, transactions=[], previous_hash="0", timestamp=1.0)
        genesis.hash = "0" * 64  # constante universal del protocolo
        self.chain.append(genesis)
        self.storage.save_block(genesis)

    # ── Validación de transacciones ───────────────────────────────────────

    def validate_transaction(self, tx: Transaction) -> bool:
        """
        Valida una transacción:
          1. Coinbase: siempre aceptada.
          2. Saldo suficiente.
          3. Prueba ZK-STARK (StarkVerifier o ZKEngine completo si hay criterion_params).
        """
        print(f"\n[Consenso] Verificando TX {tx.tx_id[:8]}...")

        # 1. Transacciones de emisión (Coinbase / Faucet)
        if not tx.sender_m3:
            print("  -> ACEPTADA: Transacción Coinbase.")
            return True

        # 2. Verificar saldo
        balance = self.state_db.get_balance(tx.sender_m3)
        total_required = tx.amount + tx.fee
        if balance < total_required:
            print(f"  -> RECHAZADA: Saldo insuficiente ({balance} < {total_required}).")
            return False

        # 3. Construir tx_hash reproducible
        payload_dict = {
            "sender_m3": tx.sender_m3,
            "receiver_m3": tx.receiver_m3,
            "amount": tx.amount,
            "fee": tx.fee,
            "payload": tx.payload,
        }
        tx_hash = hashlib.sha256(
            json.dumps(payload_dict, sort_keys=True, separators=(",",":")).encode()
        ).hexdigest()

        # 4. Verificación ZK
        sig = tx.signature_data
        is_valid = self._verify_signature(sig, tx.sender_m3, tx_hash)

        if not is_valid:
            print("  -> RECHAZADA: Falla en la prueba ZK-STARK.")
            return False

        print("  -> ACEPTADA: Prueba ZK verificada.")
        return True

    def _verify_signature(
        self,
        sig: dict,
        sender_m3: list,
        tx_hash: str,
    ) -> bool:
        """
        Delega la verificación al motor apropiado según los campos disponibles.
        """
        # Modo Compacto F4 (Zero-Knowledge real, alta eficiencia)
        if "criterion_params" in sig and "audit_point" in sig:
            try:
                from core.verifier import CriterionParams
                from crypto.zkp import ZKEngine

                params = CriterionParams.from_dict(sig["criterion_params"])
                return ZKEngine.verify_proof(
                    proof=sig,
                    public_m3=sender_m3,
                    tx_hash=tx_hash,
                    criterion_params=params,
                    N_total=400,  # ZKEngine.N_PROOF
                )
            except Exception as e:
                print(f"  [ZK] Excepción en modo compacto: {e}")
                return False

        # Modo legacy (compatibilidad hacia atrás)
        from crypto.stark_core import StarkVerifier

        return StarkVerifier.verify(sig, sender_m3, tx_hash)

    # ── Añadir bloque ──────────────────────────────────────────────────────

    def add_block(self, block: Block) -> bool:
        prev = self.chain[-1]

        if block.index != prev.index + 1:
            print(f"[Cadena] Rechazo: índice {block.index} != {prev.index + 1}")
            return False

        if block.previous_hash != prev.hash:
            print(f"[Cadena] Rechazo: linaje roto.")
            return False

        if block.hash != block.calculate_hash():
            print(f"[Cadena] Rechazo: hash del bloque inválido.")
            return False

        for tx in block.transactions:
            if not self.validate_transaction(tx):
                print(f"[Cadena] Rechazo: TX {tx.tx_id[:8]} falló validación ZK.")
                return False

        # Aplicar estado
        for tx in block.transactions:
            self.state_db.apply_transaction(
                tx.tx_id, tx.sender_m3, tx.receiver_m3, tx.amount, tx.payload, tx.fee
            )

        self.chain.append(block)
        self.storage.save_block(block)
        return True

    def add_new_transaction(self, tx: Transaction) -> bool:
        if self.validate_transaction(tx):
            self.unconfirmed_transactions.append(tx)
            return True
        return False

    def replace_chain(self, new_blocks_list: list) -> bool:
        """
        Regla de Cadena Más Larga (Longest Chain Rule).
        Evalúa y reemplaza el historial completo si hay un fork válido y más pesado.
        """
        if len(new_blocks_list) <= len(self.chain):
            return False  # La cadena local es igual o superior. Ignorar.

        print(
            f"\n[Consenso] ⚖️ Evaluando bifurcación: Local ({len(self.chain)}) vs Red ({len(new_blocks_list)})"
        )

        # 1. Validación Estructural de la nueva rama
        for i in range(1, len(new_blocks_list)):
            prev = new_blocks_list[i - 1]
            curr = new_blocks_list[i]
            if curr.previous_hash != prev.hash:
                print(
                    f"  -> [Rechazo] Linaje roto en el bloque {curr.index} de la cadena propuesta."
                )
                return False
            if curr.hash != curr.calculate_hash():
                print(
                    f"  -> [Rechazo] Hash criptográfico inválido en bloque {curr.index}."
                )
                return False

        print(
            "[Consenso] 🔄 Bifurcación ganadora. Iniciando Rollback de estado global..."
        )

        # 2. Reset de Estado Inmutable en Disco
        self.storage.clear_all()
        self.chain = []

        # Reiniciar la capa de estado en memoria (Máquina Virtual y Saldos)
        from blockchain.state import StateDB

        self.state_db = StateDB(self.storage)

        # 3. Re-aplicación del Libro Mayor (State Replay)
        for block in new_blocks_list:
            for tx in block.transactions:
                self.state_db.apply_transaction(
                    tx.tx_id,
                    tx.sender_m3,
                    tx.receiver_m3,
                    tx.amount,
                    tx.payload,
                    tx.fee,
                )
            self.chain.append(block)
            self.storage.save_block(block)

        print(
            f"[Consenso] ✓ Reorganización exitosa. Nueva altura del ledger: {len(self.chain)}"
        )
        return True
