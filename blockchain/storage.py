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
from contextlib import contextmanager


class Storage:
    def __init__(self, db_path: str = "node_data.db"):
        self.db_path = db_path
        self._local = threading.local()
        self._create_tables()

    def _in_atomic(self) -> bool:
        return bool(getattr(self._local, "atomic_depth", 0))

    @contextmanager
    def atomic(self):
        """Group ledger writes in one SQLite transaction."""
        conn = self._conn()
        depth = getattr(self._local, "atomic_depth", 0)
        if depth:
            self._local.atomic_depth = depth + 1
            try:
                yield conn
            finally:
                self._local.atomic_depth -= 1
            return
        self._local.atomic_depth = 1
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        else:
            conn.commit()
        finally:
            self._local.atomic_depth = 0

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
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            raise ValueError("El crédito debe ser un entero positivo")
        def _credit(conn):
            current = conn.execute(
                "SELECT balance FROM balances WHERE tensor_hash=?", (tensor_hash,)
            ).fetchone()
            if current and current[0] > (2**63 - 1) - amount:
                raise ValueError("El crédito excede el rango monetario")
            conn.execute(
                "INSERT INTO balances(tensor_hash, balance) VALUES(?, ?) "
                "ON CONFLICT(tensor_hash) DO UPDATE SET balance = balance + ?",
                (tensor_hash, amount, amount),
            )
        if self._in_atomic():
            _credit(self._conn())
            return
        with self._conn() as conn:
            _credit(conn)

    def transfer(self, sender_hash: str, receiver_hash: str, amount: int, fee: int = 0):
        """
        Transfiere amount desde sender a receiver, deduciendo fee del sender.
        Atómica — ambas operaciones en la misma transacción SQLite.
        """
        if (not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0
                or not isinstance(fee, int) or isinstance(fee, bool) or fee < 0):
            raise ValueError("Monto/comisión inválidos")

        def _transfer(conn):
            receiver = conn.execute(
                "SELECT balance FROM balances WHERE tensor_hash=?", (receiver_hash,)
            ).fetchone()
            if receiver_hash != sender_hash and receiver and receiver[0] > (2**63 - 1) - amount:
                raise ValueError("El receptor excedería el rango monetario")
            cur = conn.execute(
                "UPDATE balances SET balance = balance - ? "
                "WHERE tensor_hash = ? AND balance >= ?",
                (amount + fee, sender_hash, amount + fee),
            )
            if cur.rowcount == 0:
                raise ValueError(f"Saldo insuficiente para {sender_hash[:8]}")
            conn.execute(
                "INSERT INTO balances(tensor_hash, balance) VALUES(?, ?) "
                "ON CONFLICT(tensor_hash) DO UPDATE SET balance = balance + ?",
                (receiver_hash, amount, amount)
            )
        if self._in_atomic():
            _transfer(self._conn())
        else:
            with self._conn() as conn:
                _transfer(conn)

    # ── Bloques ────────────────────────────────────────────────────────────

    def save_block(self, block):
        tx_json = json.dumps([
            tx.to_dict() if hasattr(tx, "to_dict") else tx
            for tx in block.transactions
        ])
        if self._in_atomic():
            self._conn().execute(
                "INSERT OR REPLACE INTO blocks "
                "(block_index, hash, previous_hash, timestamp, transactions) "
                "VALUES (?, ?, ?, ?, ?)",
                (block.index, block.hash, block.previous_hash, block.timestamp, tx_json),
            )
            return
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO blocks "
                "(block_index, hash, previous_hash, timestamp, transactions) "
                "VALUES (?, ?, ?, ?, ?)",
                (block.index, block.hash, block.previous_hash, block.timestamp, tx_json)
            )

    def get_blocks_paginated(self, start: int = None, limit: int = 10, desc: bool = True) -> list:
        """Paginación eficiente directo desde SQLite.
        Usa conexión independiente para ser seguro en cualquier thread.
        """
        order = "DESC" if desc else "ASC"
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        try:
            if start is not None:
                op = "<=" if desc else ">="
                rows = conn.execute(
                    f"SELECT block_index, hash, previous_hash, timestamp, transactions "
                    f"FROM blocks WHERE block_index {op} ? ORDER BY block_index {order} LIMIT ?",
                    (start, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT block_index, hash, previous_hash, timestamp, transactions "
                    f"FROM blocks ORDER BY block_index {order} LIMIT ?",
                    (limit,)
                ).fetchall()
            return rows
        finally:
            conn.close()
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
        if self._in_atomic():
            self._conn().execute(
                "INSERT INTO contract_state(contract_address, state_key, state_value) "
                "VALUES(?, ?, ?) ON CONFLICT(contract_address, state_key) "
                "DO UPDATE SET state_value = excluded.state_value",
                (address, key, value),
            )
            return
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

    def backup_to(self, destination: str):
        """Create a transactionally consistent SQLite copy."""
        target = sqlite3.connect(destination, timeout=15.0)
        try:
            self._conn().backup(target)
        finally:
            target.close()

    # ── Snapshots ──────────────────────────────────────────────────────────

    def _ensure_snapshot_table(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS snapshots (
                    block_index   INTEGER PRIMARY KEY,
                    block_hash    TEXT NOT NULL,
                    timestamp     REAL NOT NULL,
                    balances_json TEXT NOT NULL,
                    fvr_json      TEXT NOT NULL
                );
            """)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(snapshots)")}
            if "contract_json" not in columns:
                conn.execute(
                    "ALTER TABLE snapshots ADD COLUMN contract_json TEXT NOT NULL DEFAULT '[]'"
                )

    def save_snapshot(self, block_index: int, block_hash: str, fvr_state: dict):
        """Guarda snapshot de balances + FVR en bloque N."""
        import time as _time
        self._ensure_snapshot_table()
        balances = self.get_all_balances()
        balances_json = json.dumps(balances)
        fvr_json = json.dumps(fvr_state)
        contract_json = json.dumps(self._conn().execute(
            "SELECT contract_address, state_key, state_value FROM contract_state "
            "ORDER BY contract_address, state_key"
        ).fetchall())
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO snapshots "
                "(block_index, block_hash, timestamp, balances_json, fvr_json, contract_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (block_index, block_hash, _time.time(), balances_json, fvr_json, contract_json)
            )
        print(f"[Snapshot] ✓ Guardado en bloque {block_index}")

    def get_latest_snapshot(self, max_index: int | None = None) -> dict | None:
        """Retorna el snapshot más reciente disponible."""
        self._ensure_snapshot_table()
        if max_index is None:
            row = self._conn().execute(
                "SELECT block_index, block_hash, balances_json, fvr_json, contract_json "
                "FROM snapshots ORDER BY block_index DESC LIMIT 1"
            ).fetchone()
        else:
            row = self._conn().execute(
                "SELECT block_index, block_hash, balances_json, fvr_json, contract_json "
                "FROM snapshots WHERE block_index <= ? "
                "ORDER BY block_index DESC LIMIT 1", (max_index,)
            ).fetchone()
        if not row:
            return None
        return {
            "block_index":   row[0],
            "block_hash":    row[1],
            "balances_json": row[2],
            "fvr_json":      row[3],
            "contract_json": row[4],
        }

    def restore_snapshot(self, snapshot: dict) -> dict:
        """Restaura balances desde un snapshot y retorna el fvr_state
        parseado (validators, slashed) para que el caller lo siembre en
        un ValidatorRegistry nuevo (ver ValidatorRegistry.seed_history).

        Antes esta función ignoraba por completo fvr_json: se guardaba
        en cada snapshot pero nunca se leía de vuelta, así que cualquier
        rollback/reorg que tomara la ruta de snapshot dejaba el FVR
        vacío o con el estado viejo del registry reutilizado — causa
        directa de que la elección de líder divergiera tras un rollback."""
        balances = json.loads(snapshot["balances_json"])
        contracts = json.loads(snapshot.get("contract_json") or "[]")
        with self._conn() as conn:
            conn.execute("DELETE FROM balances")
            conn.execute("DELETE FROM contract_state")
            conn.executemany(
                "INSERT INTO balances(tensor_hash, balance) VALUES(?, ?)",
                balances
            )
            conn.executemany(
                "INSERT INTO contract_state(contract_address, state_key, state_value) VALUES(?, ?, ?)",
                contracts,
            )
        print(f"[Snapshot] ✓ Balances restaurados desde bloque {snapshot['block_index']}")
        try:
            return json.loads(snapshot.get("fvr_json") or "{}")
        except (TypeError, ValueError):
            print("[Snapshot] ⚠️ fvr_json ilegible — FVR no restaurado desde snapshot.")
            return {}
