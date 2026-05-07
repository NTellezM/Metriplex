"""
Módulo de gestión de transacciones pendientes (Mempool) para el protocolo CAF.
Almacena transacciones validadas criptográficamente a la espera de ser minadas/validadas.
"""

from blockchain.block import Transaction
from blockchain.chain import Blockchain


class Mempool:
    def __init__(self, blockchain: Blockchain):
        self.blockchain = blockchain
        self.pending_transactions: dict[str, Transaction] = {}

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
