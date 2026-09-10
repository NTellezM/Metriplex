# SPDX-License-Identifier: MIT
#
# Metriplex Protocol
# Copyright (c) 2025-2026 NTellezM (Nelson Tellez)
#
"""
Módulo de gestión de transacciones pendientes (Mempool) para el protocolo CAF.
Almacena transacciones validadas criptográficamente a la espera de ser minadas/validadas.
"""
import time
from blockchain.block import Transaction
from blockchain.chain import Blockchain

class Mempool:
    def __init__(self, blockchain: Blockchain, persist_path: str = "mempool.json"):
        self.blockchain = blockchain
        self.persist_path = persist_path
        self.pending_transactions: dict[str, Transaction] = {}
        self._timestamps: dict[str, float] = {}
        self.ttl_seconds: int = 3600  # 1 hora
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
                calculated_id = tx.tx_id
                from blockchain.rules import TX_V2_ACTIVATION
                strict = (
                    len(self.blockchain.chain) >= TX_V2_ACTIVATION
                    or (isinstance(tx.payload, dict) and tx.payload.get("version") == 2)
                )
                if strict and tx_data.get("tx_id") != calculated_id:
                    continue
                tx.tx_id = tx_data.get("tx_id", calculated_id)
                if tx.tx_id in self.blockchain.confirmed_tx_ids:
                    continue
                self.pending_transactions[tx.tx_id] = tx
                self._timestamps[tx.tx_id] = tx_data.get("timestamp", time.time())
            print(f"[Mempool] {len(self.pending_transactions)} TXs restauradas desde disco.")
        except Exception as e:
            print(f"[Mempool] Error cargando mempool: {e}")

    def _save(self):
        try:
            import json as _json
            data = []
            for tx in self.pending_transactions.values():
                d = tx.to_dict()
                d["timestamp"] = self._timestamps.get(tx.tx_id, time.time())
                data.append(d)
            _json.dump(data, open(self.persist_path, 'w'))
        except Exception as e:
            print(f"[Mempool] Error guardando mempool: {e}")

    def cleanup_expired(self):
        now = time.time()
        expired = [
            tx_id for tx_id, ts in self._timestamps.items()
            if now - ts > self.ttl_seconds
        ]
        for tx_id in expired:
            del self.pending_transactions[tx_id]
            del self._timestamps[tx_id]
        if expired:
            print(f"[Mempool] {len(expired)} TXs expiradas eliminadas.")
            self._save()

    def add_transaction(self, tx: Transaction) -> bool:
        if (tx.tx_id in self.pending_transactions
                or tx.tx_id in getattr(self.blockchain, "confirmed_tx_ids", set())):
            return False
        from blockchain.rules import TX_V2_ACTIVATION
        if (len(self.blockchain.chain) >= TX_V2_ACTIVATION
                or (isinstance(tx.payload, dict) and tx.payload.get("version") == 2)):
            if tx.tx_id != tx.calculate_hash():
                return False
        # Las TX sin remitente son de emisión (coinbase): validate_transaction
        # las acepta sin firma, sin ZK y sin verificar saldo. El minero crea la
        # suya y la antepone al bloque directamente, sin pasar por el mempool.
        # Admitirlas aquí — único punto de entrada del API /transaction y del
        # gossip P2P NEW_TX — permitiría acuñar MPX sin límite desde fuera.
        if not tx.sender_m3:
            print("[Mempool] Rechazo: TX de emisión (coinbase) no admitida desde el exterior.")
            return False
        sender_str = str(tx.sender_m3)
        active_txs = sum(
            1
            for t in self.pending_transactions.values()
            if str(t.sender_m3) == sender_str
        )
        if active_txs >= 5:
            print(f"[Mempool] Rechazo Anti-Spam: El remitente excedió el límite de TXs pendientes.")
            return False
        if self.blockchain.validate_transaction(tx, block_index=len(self.blockchain.chain)):
            self.pending_transactions[tx.tx_id] = tx
            self._timestamps[tx.tx_id] = time.time()
            self._save()
            return True
        return False

    def get_transactions_for_block(self, limit: int = 100) -> list[Transaction]:
        """Extrae un lote de transacciones, ordenadas por comisión (fee) de mayor a menor."""
        self.cleanup_expired()
        tx_list = sorted(
            self.pending_transactions.values(), key=lambda tx: tx.fee, reverse=True
        )
        return tx_list[:limit]

    def remove_mined_transactions(self, transactions: list[Transaction]):
        """Limpia el mempool de transacciones ya incluidas en un bloque válido."""
        for tx in transactions:
            if tx.tx_id in self.pending_transactions:
                del self.pending_transactions[tx.tx_id]
                self._timestamps.pop(tx.tx_id, None)
        self._save()
