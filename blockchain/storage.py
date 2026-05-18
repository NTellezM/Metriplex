# SPDX-License-Identifier: MIT
#
# Metriplex Protocol
# Copyright (c) 2025-2026 NTellezM (Nelson Tellez)
#
"""
blockchain/storage.py — Capa de persistencia CAF v3
=====================================================
Cambios v3:
  - Connection pool via threading.local() — cada thread tiene su propia conexión
  - Un solo patrón de transacción: context manager with self._conn()
  - Eliminado update_balance (read-modify-write no atómico)
  - Eliminado wal_checkpoint manual en get_balance
  - Eliminado self.cursor compartido entre threads
  - credit() y transfer() son las únicas escrituras de balance
  - synchronous=FULL garantiza durabilidad sin checkpoint manual
"""

import json
import sqlite3
import threading


class Storage:
    def __init__(self, db_path: str = "node_data.db"):
        self.db_path = db_path
        self._local = threading.local()
        self._create_tables()

    def _conn(self) -> sqlite3.Connection:
        """
        Retorna la conexión SQLite del thread actual.
        Cada thread tiene su propia conexión — thread-safe por diseño.
        """
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self.db_path, timeout=15.0)
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = FULL;")
            conn.execute("PRAGMA cache_size = -2000;")   # 2MB por conexión
            conn.execute("PRAGMA temp_store = MEMORY;")
            conn.execute("PRAGMA foreign_keys = ON;")
            self._local.conn = conn
        return self._local.conn

    def _create_tables(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS balances (
                    tensor_hash TEXT PRIMARY KEY,
                    balance     INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS blocks (
                    block_index    INTEGER PRIMARY KEY,
                    hash           TEXT NOT NULL,
                    previous_hash  TEXT NOT NULL,
                    timestamp      REAL NOT NULL,
                    transactions   TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS contract_state (
                    contract_address TEXT NOT NULL,
                    state_key        TEXT NOT NULL,
                    state_value      TEXT,
                    PRIMARY KEY (contract_address, state_key)
                );
            """)

    # ── Balances ───────────────────────────────────────────────────────────

    def get_balance(self, tensor_hash: str) -> int:
        row = self._conn().execute(
            "SELECT balance FROM balances WHERE tensor_hash = ?",
            (tensor_hash,)
        ).fetchone()
        return row[0] if row else 0

    def credit(self, tensor_hash: str, amount: int):
        """Acredita amount al tensor_hash de forma atómica. Crea el row si no existe."""
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO balances(tensor_hash, balance) VALUES(?, ?) "
                "ON CONFLICT(tensor_hash) DO UPDATE SET balance = balance + ?",
                (tensor_hash, amount, amount)
            )

    def transfer(self, sender_hash: str, receiver_hash: str, amount: int, fee: int = 0):
        """
        Transfiere amount desde sender a receiver, deduciendo fee del sender.
        Atómica — ambas operaciones en la misma transacción SQLite.
        """
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE balances SET balance = balance - ? WHERE tensor_hash = ?",
                (amount + fee, sender_hash)
            )
            if cur.rowcount == 0:
                raise ValueError(f"Sender {sender_hash[:8]} no encontrado en balances")
            conn.execute(
                "INSERT INTO balances(tensor_hash, balance) VALUES(?, ?) "
                "ON CONFLICT(tensor_hash) DO UPDATE SET balance = balance + ?",
                (receiver_hash, amount, amount)
            )

    # ── Bloques ────────────────────────────────────────────────────────────

    def save_block(self, block):
        tx_json = json.dumps([
            tx.to_dict() if hasattr(tx, "to_dict") else tx
            for tx in block.transactions
        ])
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO blocks "
                "(block_index, hash, previous_hash, timestamp, transactions) "
                "VALUES (?, ?, ?, ?, ?)",
                (block.index, block.hash, block.previous_hash, block.timestamp, tx_json)
            )

    def get_all_blocks(self) -> list:
        return self._conn().execute(
            "SELECT block_index, hash, previous_hash, timestamp, transactions "
            "FROM blocks ORDER BY block_index ASC"
        ).fetchall()

    # ── Contratos ──────────────────────────────────────────────────────────

    def get_contract_state(self, address: str, key: str) -> str | None:
        row = self._conn().execute(
            "SELECT state_value FROM contract_state "
            "WHERE contract_address = ? AND state_key = ?",
            (address, key)
        ).fetchone()
        return row[0] if row else None

    def set_contract_state(self, address: str, key: str, value: str):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO contract_state(contract_address, state_key, state_value) "
                "VALUES(?, ?, ?) "
                "ON CONFLICT(contract_address, state_key) "
                "DO UPDATE SET state_value = excluded.state_value",
                (address, key, value)
            )

    # ── Mantenimiento ──────────────────────────────────────────────────────

    def clear_all(self):
        """Limpia estado completo para rollback/reorg."""
        with self._conn() as conn:
            conn.executescript("""
                DELETE FROM blocks;
                DELETE FROM balances;
                DELETE FROM contract_state;
            """)

    def get_all_balances(self) -> list[tuple]:
        return self._conn().execute(
            "SELECT tensor_hash, balance FROM balances ORDER BY balance DESC"
        ).fetchall()
