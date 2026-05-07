"""
Módulo de persistencia en disco para el protocolo CAF.
Utiliza SQLite para almacenar el estado global y el registro de bloques.
"""

import json
import sqlite3


class Storage:
    def __init__(self, db_path="node_data.db"):
        self.db_path = db_path
        # check_same_thread=False permite lectura asíncrona desde FastAPI
        # timeout=10.0 evita bloqueos si dos procesos chocan por milisegundos
        self.conn = sqlite3.connect(self.db_path, timeout=10.0, check_same_thread=False)

        # --- INYECCIÓN DE OPTIMIZACIÓN I/O (WAL) ---
        self.conn.execute("PRAGMA journal_mode = WAL;")
        self.conn.execute("PRAGMA synchronous = NORMAL;")
        self.conn.execute("PRAGMA cache_size = -64000;")  # 64MB de caché en RAM
        self.conn.execute("PRAGMA temp_store = MEMORY;")
        # -------------------------------------------

        self.cursor = self.conn.cursor()
        self._create_tables()

    def _create_tables(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS balances (
                tensor_hash TEXT PRIMARY KEY,
                balance INTEGER
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS blocks (
                block_index INTEGER PRIMARY KEY,
                hash TEXT,
                previous_hash TEXT,
                timestamp REAL,
                transactions TEXT
            )
        """)
        # NUEVA TABLA: Almacenamiento de estado global para Smart Contracts
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS contract_state (
                contract_address TEXT,
                state_key TEXT,
                state_value TEXT,
                PRIMARY KEY (contract_address, state_key)
            )
        """)
        self.conn.commit()

    # NUEVOS MÉTODOS PARA LA MÁQUINA VIRTUAL
    def get_contract_state(self, address: str, key: str) -> str:
        self.cursor.execute(
            "SELECT state_value FROM contract_state WHERE contract_address = ? AND state_key = ?",
            (address, key),
        )
        row = self.cursor.fetchone()
        return row[0] if row else None

    def set_contract_state(self, address: str, key: str, value: str):
        self.cursor.execute(
            """
            INSERT INTO contract_state (contract_address, state_key, state_value)
            VALUES (?, ?, ?)
            ON CONFLICT(contract_address, state_key) DO UPDATE SET state_value=excluded.state_value
        """,
            (address, key, value),
        )
        self.conn.commit()

    def get_balance(self, tensor_hash: str) -> int:
        self.cursor.execute(
            "SELECT balance FROM balances WHERE tensor_hash = ?", (tensor_hash,)
        )
        row = self.cursor.fetchone()
        return row[0] if row else 0

    def update_balance(self, tensor_hash: str, new_balance: int):
        self.cursor.execute(
            """
            INSERT INTO balances (tensor_hash, balance)
            VALUES (?, ?)
            ON CONFLICT(tensor_hash) DO UPDATE SET balance=excluded.balance
        """,
            (tensor_hash, new_balance),
        )
        self.conn.commit()

    def save_block(self, block):
        # Serializar transacciones a texto para almacenamiento relacional
        tx_json = json.dumps(
            [
                tx.to_dict() if hasattr(tx, "to_dict") else tx
                for tx in block.transactions
            ]
        )
        self.cursor.execute(
            """
            INSERT INTO blocks (block_index, hash, previous_hash, timestamp, transactions)
            VALUES (?, ?, ?, ?, ?)
        """,
            (block.index, block.hash, block.previous_hash, block.timestamp, tx_json),
        )
        self.conn.commit()

    def get_all_blocks(self) -> list:
        self.cursor.execute(
            "SELECT block_index, hash, previous_hash, timestamp, transactions FROM blocks ORDER BY block_index ASC"
        )
        return self.cursor.fetchall()

    def clear_all(self):
        """Limpia el estado global y el registro de bloques para aplicar un Rollback/Reorg."""
        self.cursor.execute("DELETE FROM blocks")
        self.cursor.execute("DELETE FROM balances")
        self.cursor.execute("DELETE FROM contract_state")
        self.conn.commit()
