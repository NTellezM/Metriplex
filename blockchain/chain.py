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
from blockchain.validator_registry import ValidatorRegistry


class Blockchain:
    def __init__(self, storage: Storage):
        self.storage = storage
        self.validator_registry = ValidatorRegistry()
        self.state_db = StateDB(self.storage, self.validator_registry)
        self.chain = []
        self.confirmed_tx_ids = set()
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
                if tx.sender_m3:
                    self.confirmed_tx_ids.add(tx.tx_id)

            block = Block(index, transactions, prev_hash, timestamp)
            block.hash = b_hash
            self.chain.append(block)
            for tx in transactions:
                self.validator_registry.process_tx(tx, index)

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

    def validate_transaction(self, tx: Transaction, block_index: int = 0) -> bool:
        """
        Valida una transacción:
          1. Coinbase: siempre aceptada.
          2. Saldo suficiente.
          3. Prueba ZK-STARK (StarkVerifier o ZKEngine completo si hay criterion_params).
        """
        print(f"\n[Consenso] Verificando TX {tx.tx_id[:8]}...")

        from blockchain.rules import MAX_MONEY_RAW, TX_V2_ACTIVATION
        is_int = lambda value: isinstance(value, int) and not isinstance(value, bool)
        if not is_int(tx.amount) or not is_int(tx.fee):
            print("  -> RECHAZADA: monto o comisión no son enteros.")
            return False
        if tx.amount < 0 or tx.fee < 0 or tx.amount > MAX_MONEY_RAW or tx.fee > MAX_MONEY_RAW:
            print("  -> RECHAZADA: monto o comisión fuera de rango.")
            return False
        if tx.amount + tx.fee > MAX_MONEY_RAW:
            print("  -> RECHAZADA: suma de monto y comisión fuera de rango.")
            return False

        # 1. Transacciones de emisión (Coinbase / Faucet)
        if not tx.sender_m3:
            return tx.amount > 0 and tx.fee == 0

        op = tx.payload.get("op") if isinstance(tx.payload, dict) else None
        if tx.amount == 0 and op not in {"VALIDATOR_EXIT", "VALIDATOR_UPDATE", "VALIDATOR_GOVERNANCE_EXIT"}:
            print("  -> RECHAZADA: el monto debe ser positivo.")
            return False

        is_v2 = isinstance(tx.payload, dict) and tx.payload.get("version") == 2
        if block_index >= TX_V2_ACTIVATION or is_v2:
            from blockchain.tx_canonical import validate_v2_payload
            if not validate_v2_payload(tx.payload):
                print("  -> RECHAZADA: falta sobre firmado v2 (chain_id/nonce).")
                return False

        # Operaciones de protocolo (registro/salida/actualización/gobernanza).
        from blockchain.protocol_auth import (
            PROTOCOL_OPS, PROTOCOL_SIG_ACTIVATION, protocol_op_hash,
        )
        if tx.payload and tx.payload.get("op") in PROTOCOL_OPS:
            op = tx.payload.get("op")
            if block_index < PROTOCOL_SIG_ACTIVATION:
                # Reglas legacy — necesarias para el replay de bloques históricos.
                print(f"  -> ACEPTADA (legacy): Operación de protocolo ({op}).")
                return True
            # Reglas estrictas: firma ZK del emisor sobre el mensaje canónico.
            op_hash = protocol_op_hash(
                tx.sender_m3, tx.payload, tx.amount, tx.receiver_m3, tx.fee
            )
            if not self._verify_signature(tx.signature_data, tx.sender_m3, op_hash, block_index):
                print(f"  -> RECHAZADA: firma inválida en operación de protocolo ({op}).")
                return False
            if op == "VALIDATOR_REGISTER":
                from blockchain.validator_registry import VALIDATOR_STAKE_REQUIRED
                bal = self.state_db.get_balance(tx.sender_m3)
                if bal < VALIDATOR_STAKE_REQUIRED:
                    print(f"  -> RECHAZADA: stake real insuficiente ({bal} < {VALIDATOR_STAKE_REQUIRED}).")
                    return False
                if block_index >= TX_V2_ACTIVATION:
                    from blockchain.rules import STAKE_VAULT_M3_HASH
                    if (tx.amount != VALIDATOR_STAKE_REQUIRED
                            or self.get_tensor_hash(tx.receiver_m3) != STAKE_VAULT_M3_HASH
                            or self.get_tensor_hash(tx.sender_m3) in self.validator_registry.validators):
                        print("  -> RECHAZADA: registro de validador no bloquea el stake en el vault.")
                        return False
            elif op == "VALIDATOR_EXIT" and block_index >= TX_V2_ACTIVATION:
                from blockchain.rules import STAKE_VAULT_M3_HASH
                sender_hash = self.get_tensor_hash(tx.sender_m3)
                if (sender_hash not in self.validator_registry.validators
                        or self.get_tensor_hash(tx.receiver_m3) != STAKE_VAULT_M3_HASH
                        or tx.amount != 0 or tx.fee != 0):
                    print("  -> RECHAZADA: salida de validador inválida.")
                    return False
            # Los votos de VALIDATOR_GOVERNANCE_EXIT se verifican al aplicar (state.py).
            print(f"  -> ACEPTADA: Operación de protocolo firmada ({op}).")
            return True



        # 2. Verificar timestamp anti-replay (TTL 10 minutos)
        import time as _time
        tx_ts = tx.payload.get("timestamp") if tx.payload else None
        if tx_ts:
            age = _time.time() - float(tx_ts)
            if age > 600:  # 10 minutos
                print(f"  -> RECHAZADA: TX expirada (age={int(age)}s > 600s).")
                return False
            if age < -60:  # reloj del cliente adelantado >1 min
                print(f"  -> RECHAZADA: TX timestamp futuro (age={int(age)}s).")
                return False
        # 3. Verificar saldo
        balance = self.state_db.get_balance(tx.sender_m3)
        total_required = tx.amount + tx.fee
        if balance < total_required:
            print(f"  -> RECHAZADA: Saldo insuficiente ({balance} < {total_required}).")
            return False

        # 3. tx_hash reproducible vía la serialización canónica ÚNICA
        # (misma que el cliente, el relayer y validate_zk_only).
        from blockchain.tx_canonical import canonical_tx_hash, canonical_tx_hash_v2
        if is_v2:
            tx_hash = canonical_tx_hash_v2(
                tx.sender_m3, tx.receiver_m3, tx.amount, tx.fee, tx.payload
            )
        else:
            tx_hash = canonical_tx_hash(tx.sender_m3, tx.receiver_m3, tx.amount, tx.fee)

        # 4. Verificación ZK
        sig = tx.signature_data
        is_valid = self._verify_signature(sig, tx.sender_m3, tx_hash, block_index)
        if not is_valid:
            print("  -> RECHAZADA: Falla en la prueba ZK-STARK.")
            return False

        print("  -> ACEPTADA: Prueba ZK verificada.")
        return True

    def validate_zk_only(self, tx, block_index: int = 0) -> bool:
        """Valida solo la prueba ZK (sin saldo). Usa la MISMA serialización
        canónica que validate_transaction y el cliente, resolviendo la antigua
        discrepancia payload=None vs payload real que obligaba a saltarse la
        verificación en replace_chain."""
        if not tx.sender_m3:
            return True
        if tx.signature_data.get("type") == "COINBASE":
            return True
        # Operaciones de protocolo: su firma es sobre protocol_op_hash y se
        # verifican en add_block (con gating de activación); aquí se difieren.
        from blockchain.protocol_auth import PROTOCOL_OPS
        if tx.payload and isinstance(tx.payload, dict) and tx.payload.get("op") in PROTOCOL_OPS:
            return True
        from blockchain.rules import TX_V2_ACTIVATION
        from blockchain.tx_canonical import canonical_tx_hash, canonical_tx_hash_v2, validate_v2_payload
        is_v2 = isinstance(tx.payload, dict) and tx.payload.get("version") == 2
        if block_index >= TX_V2_ACTIVATION or is_v2:
            if not validate_v2_payload(tx.payload):
                return False
        if is_v2:
            tx_hash = canonical_tx_hash_v2(
                tx.sender_m3, tx.receiver_m3, tx.amount, tx.fee, tx.payload
            )
        else:
            tx_hash = canonical_tx_hash(tx.sender_m3, tx.receiver_m3, tx.amount, tx.fee)
        return self._verify_signature(tx.signature_data, tx.sender_m3, tx_hash, block_index)

    def _verify_signature(

        self,
        sig: dict,
        sender_m3: list,
        tx_hash: str,
        block_index: int = None,
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
                    N_total=2000,  # match attractor size
                    block_index=block_index,
                )
            except Exception as e:
                print(f"  [ZK] Excepción en modo compacto: {e}")
                return False

        # Modo legacy (compatibilidad hacia atrás)
        from crypto.stark_core import StarkVerifier

        return StarkVerifier.verify(sig, sender_m3, tx_hash)

    # ── Añadir bloque ──────────────────────────────────────────────────────

    def _check_block_coinbase(self, block) -> bool:
        """Unicidad + monto de la coinbase según la fórmula de emisión.
        Reutilizado por add_block y por la validación de reorg."""
        from blockchain.emission import COINBASE_ACTIVATION, expected_coinbase_reward, m3_hash as _m3h
        coinbases = [tx for tx in block.transactions if not tx.sender_m3]
        from blockchain.rules import TX_V2_ACTIVATION
        if block.index >= TX_V2_ACTIVATION and len(coinbases) != 1:
            print(f"[Cadena] Rechazo: bloque {block.index} requiere exactamente una coinbase.")
            return False
        if len(coinbases) > 1:
            print(f"[Cadena] Rechazo: {len(coinbases)} coinbases en el bloque {block.index} (máx 1).")
            return False
        if block.index >= COINBASE_ACTIVATION and coinbases:
            cb = coinbases[0]
            if block.transactions[0] is not cb:
                print(f"[Cadena] Rechazo: la coinbase no está en la posición 0.")
                return False
            registry = self.state_db.validator_registry
            leader_hash = _m3h(cb.receiver_m3) if cb.receiver_m3 else ""
            if leader_hash not in registry.validators:
                print(f"[Cadena] Rechazo: receptor de coinbase {leader_hash[:8]} no es validador registrado.")
                return False
            expected = expected_coinbase_reward(registry, block.index, leader_hash)
            if int(cb.amount) != expected:
                print(f"[Cadena] Rechazo: monto de coinbase {cb.amount} != esperado {expected} "
                      f"(bloque {block.index}, lider {leader_hash[:8]}).")
                return False
            if block.index >= TX_V2_ACTIVATION:
                import time
                from blockchain.block_auth import BLOCK_TIME_SECONDS, expected_leader, producer_hash
                if block.timestamp <= self.chain[-1].timestamp:
                    print("[Cadena] Rechazo: timestamp no avanza.")
                    return False
                if int(block.timestamp // BLOCK_TIME_SECONDS) <= int(
                    self.chain[-1].timestamp // BLOCK_TIME_SECONDS
                ):
                    print("[Cadena] Rechazo: ya existe un bloque en este slot.")
                    return False
                if block.timestamp > time.time() + 120:
                    print("[Cadena] Rechazo: timestamp demasiado futuro.")
                    return False
                elected = expected_leader(
                    self.chain, self.validator_registry, block.timestamp
                )
                if elected != leader_hash:
                    print("[Cadena] Rechazo: la coinbase no pertenece al líder del slot.")
                    return False
                if not self._verify_signature(
                    cb.signature_data, cb.receiver_m3, producer_hash(block), block.index
                ):
                    print("[Cadena] Rechazo: autenticación del productor inválida.")
                    return False
        return True

    def _check_protocol_op(self, tx, block_index: int) -> bool:
        """Firma de una operación de protocolo (gateada por activación)."""
        from blockchain.protocol_auth import (
            PROTOCOL_SIG_ACTIVATION, protocol_op_hash,
        )
        if block_index < PROTOCOL_SIG_ACTIVATION:
            return True  # legacy
        op_hash = protocol_op_hash(
            tx.sender_m3, tx.payload, tx.amount, tx.receiver_m3, tx.fee
        )
        if not self._verify_signature(tx.signature_data, tx.sender_m3, op_hash, block_index):
            print(f"[Cadena] Rechazo (reorg): firma inválida en op de protocolo.")
            return False
        if tx.payload.get("op") == "VALIDATOR_REGISTER":
            from blockchain.validator_registry import VALIDATOR_STAKE_REQUIRED
            if self.state_db.get_balance(tx.sender_m3) < VALIDATOR_STAKE_REQUIRED:
                print(f"[Cadena] Rechazo (reorg): stake real insuficiente en REGISTER.")
                return False
            from blockchain.rules import STAKE_VAULT_M3_HASH, TX_V2_ACTIVATION
            if block_index >= TX_V2_ACTIVATION and (
                tx.amount != VALIDATOR_STAKE_REQUIRED
                or self.get_tensor_hash(tx.receiver_m3) != STAKE_VAULT_M3_HASH
                or self.get_tensor_hash(tx.sender_m3) in self.validator_registry.validators
            ):
                return False
        elif tx.payload.get("op") == "VALIDATOR_EXIT":
            from blockchain.rules import STAKE_VAULT_M3_HASH, TX_V2_ACTIVATION
            if block_index >= TX_V2_ACTIVATION and (
                self.get_tensor_hash(tx.sender_m3) not in self.validator_registry.validators
                or self.get_tensor_hash(tx.receiver_m3) != STAKE_VAULT_M3_HASH
                or tx.amount != 0 or tx.fee != 0
            ):
                return False
        return True

    def _validate_block_for_reorg(self, block) -> bool:
        """Valida un bloque candidato antes de aplicarlo en un reorg: integridad
        del hash, firmas de TX (serialización canónica) y coinbase. Cierra el
        bypass por el que replace_chain aplicaba estado sin validar."""
        from blockchain.protocol_auth import PROTOCOL_OPS
        if block.index == 0:
            return (
                block.hash == "0" * 64
                and block.previous_hash == "0"
                and block.timestamp == 1.0
                and not block.transactions
            )
        if block.hash != block.calculate_hash():
            print(f"[Cadena] Rechazo (reorg): hash inválido en bloque {block.index}.")
            return False
        for tx in block.transactions:
            from blockchain.rules import MAX_MONEY_RAW
            if (not isinstance(tx.amount, int) or isinstance(tx.amount, bool)
                    or not isinstance(tx.fee, int) or isinstance(tx.fee, bool)
                    or tx.amount < 0 or tx.fee < 0
                    or tx.amount + tx.fee > MAX_MONEY_RAW):
                return False
            if not tx.sender_m3:
                continue  # coinbase — se valida abajo por monto/unicidad
            if tx.payload and isinstance(tx.payload, dict) and tx.payload.get("op") in PROTOCOL_OPS:
                if not self._check_protocol_op(tx, block.index):
                    return False
            elif not self.validate_zk_only(tx, block.index):
                print(f"[Cadena] Rechazo (reorg): firma de TX inválida en bloque {block.index}.")
                return False
        return self._check_block_coinbase(block)

    def add_block(self, block: Block, skip_zk: bool = False) -> bool:
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

        block_ids = [tx.tx_id for tx in block.transactions if tx.sender_m3]
        from blockchain.rules import TX_V2_ACTIVATION
        if any(
            tx.tx_id != tx.calculate_hash()
            for tx in block.transactions
            if block.index >= TX_V2_ACTIVATION
            or (isinstance(tx.payload, dict) and tx.payload.get("version") == 2)
        ):
            print("[Cadena] Rechazo: tx_id no corresponde al contenido.")
            return False
        if len(block_ids) != len(set(block_ids)) or any(
            tx_id in self.confirmed_tx_ids for tx_id in block_ids
        ):
            print("[Cadena] Rechazo: transacción duplicada o ya confirmada.")
            return False

        if not skip_zk:
            for tx in block.transactions:
                if not self.validate_transaction(tx, block_index=block.index):
                    print(f"[Cadena] Rechazo: TX {tx.tx_id[:8]} falló validación ZK.")
                    return False

        # Validación de coinbase a nivel de bloque (unicidad + monto según la
        # fórmula de emisión). Se aplica SIEMPRE (aunque skip_zk), porque es una
        # regla de consenso que frena a un validador que mine un bloque con una
        # coinbase inflada o múltiple. Los bloques históricos (< activación) se
        # aceptan bajo reglas legacy.
        if not self._check_block_coinbase(block):
            return False

        # Aplicar el bloque como una sola transacción SQLite. Si una operación
        # falla, no persisten saldos parciales ni el bloque.
        import copy
        registry_backup = copy.deepcopy(self.validator_registry)
        try:
            with self.storage.atomic():
                for tx in block.transactions:
                    applied = self.state_db.apply_transaction(
                        tx.tx_id, tx.sender_m3, tx.receiver_m3,
                        tx.amount, tx.payload, tx.fee, block.index,
                    )
                    if not applied:
                        raise ValueError(f"no se pudo aplicar TX {tx.tx_id[:8]}")
                for tx in block.transactions:
                    self.validator_registry.process_tx(tx, block.index)
                self.storage.save_block(block)
        except Exception as exc:
            self.validator_registry = registry_backup
            self.state_db.validator_registry = registry_backup
            print(f"[Cadena] Rechazo: aplicación atómica falló: {exc}")
            return False
        self.chain.append(block)
        self.confirmed_tx_ids.update(block_ids)
        # Snapshot cada 1000 bloques
        if block.index > 0 and block.index % 1000 == 0:
            fvr_state = {
                "validators": {
                    k: {kk: vv for kk, vv in v.items() if kk != "m3"}
                    for k, v in self.validator_registry.validators.items()
                },
                "slashed": list(self.validator_registry.slashed),
            }
            self.storage.save_snapshot(block.index, block.hash, fvr_state)
        return True

    def add_new_transaction(self, tx: Transaction) -> bool:
        if tx.tx_id in self.confirmed_tx_ids:
            return False
        if self.validate_transaction(tx, block_index=len(self.chain)):
            self.unconfirmed_transactions.append(tx)
            return True
        return False


    def rollback_to(self, target_index: int) -> bool:
        """
        Retrocede la cadena al bloque target_index (inclusive).
        Reconstruye el estado desde el snapshot más cercano.
        Usado por el mecanismo de catch-up p2p cuando se detecta un fork.
        """
        current_tip = len(self.chain) - 1
        if target_index >= current_tip:
            return True   # nada que hacer
        if target_index < 0 or target_index >= len(self.chain):
            return False

        # Fix 5 — límite duro de profundidad. Antes rollback_to aceptaba
        # cualquier target sin límite: en una cascada de forks (bug de
        # sincronización nunca re-disparándose) el nodo podía retroceder
        # 20 bloques por iteración indefinidamente, sin fondo. Un reorg
        # más profundo que esto es indicio de que algo más está mal y
        # requiere intervención manual, no un rollback automático más.
        MAX_REORG_DEPTH = 200
        reorg_depth = current_tip - target_index
        if reorg_depth > MAX_REORG_DEPTH:
            print(f"[Cadena] ⛔ Rollback rechazado: profundidad {reorg_depth} > "
                  f"MAX {MAX_REORG_DEPTH} — requiere intervención manual.")
            return False

        print(f"[Cadena] Rollback: bloque {current_tip} → {target_index}")

        # Bloques que queremos conservar
        keep_blocks = list(self.chain[:target_index + 1])

        # Snapshot más cercano por debajo del target
        from blockchain.state import StateDB
        from blockchain.validator_registry import ValidatorRegistry
        snapshot = self.storage.get_latest_snapshot(target_index)

        # Reset completo (igual que replace_chain)
        self.storage.clear_all()
        self.chain = []
        # Fix 3 — instanciar un ValidatorRegistry NUEVO en vez de reutilizar
        # self.validator_registry. Antes el registry conservaba TODO su
        # estado acumulado hasta el tip viejo (incluyendo los bloques que
        # se están descartando en este rollback) y ENCIMA se le
        # reaplicaban vía process_tx las transacciones de los bloques
        # conservados posteriores al snapshot. El resultado era un
        # registry que no correspondía a ningún estado real de la cadena
        # — λ_mean y elección de líder divergían entre el nodo que hizo
        # rollback y el que no, generando un fork nuevo a partir del
        # intento de reparar el anterior. Ahora se reconstruye desde
        # cero, igual que hace load_chain_from_disk al arrancar el nodo.
        self.validator_registry = ValidatorRegistry()
        self.state_db = StateDB(self.storage, self.validator_registry)

        if (snapshot and snapshot["block_index"] <= target_index
                and snapshot["block_index"] < len(keep_blocks)
                and keep_blocks[snapshot["block_index"]].hash == snapshot["block_hash"]):
            snap_idx = snapshot["block_index"]
            fvr_state = self.storage.restore_snapshot(snapshot)
            if fvr_state.get("validators"):
                self.validator_registry.seed_history(
                    snap_idx, fvr_state["validators"], fvr_state.get("slashed")
                )
            for blk in keep_blocks[:snap_idx + 1]:
                self.chain.append(blk)
                self.storage.save_block(blk)
            replay_start = snap_idx + 1
        else:
            # Sin snapshot válido — empezar desde génesis
            genesis = keep_blocks[0]
            self.chain.append(genesis)
            self.storage.save_block(genesis)
            replay_start = 1

        # Replay de transacciones para reconstruir estado
        for blk in keep_blocks[replay_start:]:
            self.chain.append(blk)
            self.storage.save_block(blk)
            for tx in blk.transactions:
                self.state_db.apply_transaction(
                    tx.tx_id, tx.sender_m3, tx.receiver_m3,
                    tx.amount, tx.payload, tx.fee, blk.index
                )
            for tx in blk.transactions:
                self.validator_registry.process_tx(tx, blk.index)

        self.confirmed_tx_ids = {
            tx.tx_id for blk in self.chain for tx in blk.transactions if tx.sender_m3
        }

        print(f"[Cadena] Rollback completado. Tip: bloque {self.chain[-1].index}")
        return True

    def replace_chain(self, new_blocks_list: list) -> bool:
        """
        Regla de Cadena Más Larga (Longest Chain Rule).
        Evalúa y reemplaza el historial completo si hay un fork válido y más pesado.
        """
        if len(new_blocks_list) < len(self.chain):
            return False  # La cadena local es superior. Ignorar.

        # Empate: la cadena con hash del último bloque lexicográficamente menor gana
        if len(new_blocks_list) == len(self.chain):
            local_last = self.chain[-1].hash
            remote_last = new_blocks_list[-1].hash
            if local_last == remote_last:
                return False  # Misma cadena
            if local_last < remote_last:
                return False  # Local gana hash menor
            # Remote gana el desempate — continuar con el reemplazo

        # Límite de profundidad de reorganización
        MAX_REORG_DEPTH = 200
        diverge_at = min(len(self.chain), len(new_blocks_list))
        for i in range(min(len(self.chain), len(new_blocks_list))):
            if self.chain[i].hash != new_blocks_list[i].hash:
                diverge_at = i
                break
        reorg_depth = len(self.chain) - diverge_at
        if reorg_depth > MAX_REORG_DEPTH:
            print(f"[Consenso] ⛔ Reorg rechazado: profundidad {reorg_depth} > MAX {MAX_REORG_DEPTH}")
            return False

        print(f"\n[Consenso] Evaluando rama remota; profundidad={reorg_depth}")
        if not new_blocks_list or not self._validate_block_for_reorg(new_blocks_list[0]):
            return False
        for i, block in enumerate(new_blocks_list):
            if block.index != i:
                print(f"[Consenso] Reorg rechazado: índice no canónico en posición {i}.")
                return False
            if i and (block.previous_hash != new_blocks_list[i - 1].hash
                      or block.hash != block.calculate_hash()):
                print(f"[Consenso] Reorg rechazado: bloque {i} sin integridad.")
                return False

        # Validate the divergent branch against a private database copy. An
        # invalid candidate can no longer erase or partially rewrite live state.
        import os
        import tempfile
        fd, staging_path = tempfile.mkstemp(prefix="metriplex-reorg-", suffix=".db")
        os.close(fd)
        try:
            self.storage.backup_to(staging_path)
            staged = Blockchain(Storage(staging_path))
            ancestor = diverge_at - 1
            if not staged.rollback_to(ancestor):
                return False
            for block in new_blocks_list[diverge_at:]:
                if not staged._validate_block_for_reorg(block):
                    return False
                if not staged.add_block(block, skip_zk=True):
                    return False
        finally:
            for suffix in ("", "-wal", "-shm"):
                try:
                    os.unlink(staging_path + suffix)
                except FileNotFoundError:
                    pass

        ancestor = diverge_at - 1
        if ancestor < self.chain[-1].index and not self.rollback_to(ancestor):
            return False
        for block in new_blocks_list[diverge_at:]:
            if not self.add_block(block, skip_zk=True):
                raise RuntimeError("La rama validada no pudo aplicarse al estado local")
        print(f"[Consenso] ✓ Reorganización exitosa. Nueva altura: {self.chain[-1].index}")
        return True
