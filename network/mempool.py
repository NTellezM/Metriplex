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
Módulo de gestión de transacciones pendientes (Mempool) para el protocolo CAF.
Almacena transacciones validadas criptográficamente a la espera de ser minadas/validadas.
"""

from blockchain.block import Transaction
from blockchain.chain import Blockchain


class Mempool:
    def __init__(self, blockchain: Blockchain, persist_path: str = "mempool.json"):
        self.blockchain = blockchain
        self.persist_path = persist_path
        self.pending_transactions: dict[str, Transaction] = {}
        self._load()

    def _load(self):
        import os
        if not os.path.exists(self.persist_path):
            return
        try:
            import json as _json
            data = _json.load(open(self.persist_path))
            for tx_data in data:
                tx = Transaction(
                    sender_m3=tx_data["sender_m3"],
                    receiver_m3=tx_data["receiver_m3"],
                    amount=tx_data["amount"],
                    fee=tx_data.get("fee", 0),
                    signature_data=tx_data.get("signature_data", {}),
                    payload=tx_data.get("payload", {}),
                )
                tx.tx_id = tx_data["tx_id"]
                self.pending_transactions[tx.tx_id] = tx
            print(f"[Mempool] {len(self.pending_transactions)} TXs restauradas desde disco.")
        except Exception as e:
            print(f"[Mempool] Error cargando mempool: {e}")

    def _save(self):
        try:
            import json as _json
            data = [tx.to_dict() for tx in self.pending_transactions.values()]
            _json.dump(data, open(self.persist_path, 'w'))
        except Exception as e:
            print(f"[Mempool] Error guardando mempool: {e}")

    def add_transaction(self, tx: Transaction) -> bool:
        if tx.tx_id in self.pending_transactions:
            return False

        # NUEVO: Mecanismo Anti-Spam (Máximo 5 transacciones pendientes por cuenta)
        if tx.sender_m3:
            sender_str = str(tx.sender_m3)
            active_txs = sum(
                1
                for t in self.pending_transactions.values()
                if str(t.sender_m3) == sender_str
            )
            if active_txs >= 5:
                print(
                    f"[Mempool] Rechazo Anti-Spam: El remitente excedió el límite de TXs pendientes."
                )
                return False

        if self.blockchain.validate_transaction(tx):
            self.pending_transactions[tx.tx_id] = tx
            self._save()
            return True

        return False

    def get_transactions_for_block(self, limit: int = 100) -> list[Transaction]:
        """Extrae un lote de transacciones, ordenadas por comisión (fee) de mayor a menor."""
        tx_list = sorted(
            self.pending_transactions.values(), key=lambda tx: tx.fee, reverse=True
        )
        return tx_list[:limit]

    def remove_mined_transactions(self, transactions: list[Transaction]):
        """
        Limpia el mempool de transacciones que ya fueron incluidas en un bloque válido.
        """
        for tx in transactions:
            if tx.tx_id in self.pending_transactions:
                del self.pending_transactions[tx.tx_id]
        self._save()
