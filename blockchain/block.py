"""
Módulo de estructura de bloques para el protocolo CAF.
Define los objetos inmutables que componen el libro mayor distribuido.
"""

import hashlib
import json
import time


class Transaction:
    def __init__(
        self,
        sender_m3: list,
        receiver_m3: list,
        amount: int,
        signature_data: dict,
        payload: dict = None,
        fee: int = 0,  # NUEVO: Comisión de red
    ):
        self.sender_m3 = sender_m3
        self.receiver_m3 = receiver_m3
        self.amount = amount
        self.fee = fee
        self.signature_data = signature_data
        self.payload = payload or {}
        self.tx_id = self.calculate_hash()

    def calculate_hash(self) -> str:
        tx_data = {
            "sender_m3": self.sender_m3,
            "receiver_m3": self.receiver_m3,
            "amount": self.amount,
            "fee": self.fee,  # NUEVO: El fee es parte del compromiso ZK
            "payload": self.payload,
        }
        tx_str = json.dumps(tx_data, sort_keys=True).encode()
        return hashlib.sha256(tx_str).hexdigest()

    def to_dict(self):
        return {
            "tx_id": self.tx_id,
            "sender_m3": self.sender_m3,
            "receiver_m3": self.receiver_m3,
            "amount": self.amount,
            "fee": self.fee,  # NUEVO
            "signature_data": self.signature_data,
            "payload": self.payload,
        }


class Block:
    def __init__(
        self,
        index: int,
        transactions: list[Transaction],
        previous_hash: str,
        timestamp: float = None,
    ):
        self.index = index
        self.timestamp = timestamp or time.time()
        self.transactions = transactions
        self.previous_hash = previous_hash
        self.nonce = 0
        self.hash = self.calculate_hash()

    def calculate_hash(self) -> str:
        block_content = json.dumps(
            {
                "index": self.index,
                "timestamp": self.timestamp,
                "transactions": [tx.to_dict() for tx in self.transactions],
                "previous_hash": self.previous_hash,
                "nonce": self.nonce,
            },
            sort_keys=True,
        ).encode()
        return hashlib.sha256(block_content).hexdigest()

    def to_dict(self) -> dict:
        """Serializa el bloque a dict JSON-compatible. Requerido por /blocks y P2P."""
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "hash": self.hash,
            "previous_hash": self.previous_hash,
            "nonce": self.nonce,
            "transactions": [
                tx.to_dict() if hasattr(tx, "to_dict") else tx
                for tx in self.transactions
            ],
        }
