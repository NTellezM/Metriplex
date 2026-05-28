# SPDX-License-Identifier: MIT
#
# Metriplex Protocol
# Copyright (c) 2025-2026 NTellezM (Nelson Tellez)
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software to use, copy, modify, and distribute this
# software under the terms of the MIT License.
#
import hashlib
import json

from core.vm import CAFVirtualMachine

from blockchain.storage import Storage


class StateDB:
    def __init__(self, storage: Storage, validator_registry=None):
        self.storage = storage
        self.validator_registry = validator_registry
        self.vm = CAFVirtualMachine(self.storage)

    def _hash_tensor(self, m3_tensor: list) -> str:
        tensor_str = json.dumps(m3_tensor, sort_keys=True, separators=(",",":")).encode()
        return hashlib.sha256(tensor_str).hexdigest()

    def get_balance(self, m3_tensor: list) -> int:
        tensor_hash = self._hash_tensor(m3_tensor)
        return self.storage.get_balance(tensor_hash)

    def mint(self, m3_tensor: list, amount: int):
        tensor_hash = self._hash_tensor(m3_tensor)
        self.storage.credit(tensor_hash, amount)

    # ACTUALIZADO: Se añade tx_id y payload a los parámetros
    def apply_transaction(
        self,
        tx_id: str,
        sender_m3: list,
        receiver_m3: list,
        amount: int,
        payload: dict = None,
        fee: int = 0,
    ) -> bool:
        receiver_hash = self._hash_tensor(receiver_m3)
        sender_hash = self._hash_tensor(sender_m3) if sender_m3 else "COINBASE"

        # 1. Ejecutar Lógica de Contrato Inteligente (si existe payload)
        if payload:
            op = payload.get("op")

            # VALIDATOR_EXIT — devolver stake al sender desde el vault
            if op == "VALIDATOR_EXIT":
                from blockchain.validator_registry import VALIDATOR_STAKE_REQUIRED
                vault_hash = receiver_hash
                vault_balance = self.storage.get_balance(vault_hash)
                if vault_balance >= VALIDATOR_STAKE_REQUIRED:
                    self.storage.transfer(vault_hash, sender_hash, VALIDATOR_STAKE_REQUIRED, 0)
                    print(f"[State] VALIDATOR_EXIT: {VALIDATOR_STAKE_REQUIRED // 1073741824} MPX devueltos a {sender_hash[:8]}")
                else:
                    print(f"[State] VALIDATOR_EXIT: vault sin fondos suficientes ({vault_balance})")
                return True

            # VALIDATOR_UPDATE — actualiza lambda_value
            if op == "VALIDATOR_UPDATE":
                return True  # solo registry lo procesa, sin movimiento de fondos

            # VALIDATOR_SLASH — stake quemado
            if op == "VALIDATOR_SLASH":
                print(f"[State] VALIDATOR_SLASH: stake de {payload.get('target_m3_hash','?')[:8]} quemado.")
                return True
            # VALIDATOR_GOVERNANCE_EXIT — expulsión por votación 2/3 validadores activos
            if op == "VALIDATOR_GOVERNANCE_EXIT":
                from blockchain.validator_registry import VALIDATOR_STAKE_REQUIRED
                target = payload.get("target_m3_hash")
                votes  = payload.get("votes", [])
                if not target:
                    print("[State] GOVERNANCE_EXIT: falta target_m3_hash")
                    return False
                # Obtener validadores activos (excluir al target)
                active_hashes = set(
                    v["m3_hash"] for v in self.validator_registry.validators.values()
                    if v["m3_hash"] != target
                )
                required = 2  # mínimo 2 validadores
                # Verificar votos — contar voters únicos que están en el registry
                valid_votes = 0
                seen = set()
                for vote in votes:
                    voter = vote.get("m3_hash")
                    if not voter or voter in seen:
                        continue
                    if voter in active_hashes:
                        seen.add(voter)
                        valid_votes += 1
                if valid_votes < required:
                    print(f"[State] GOVERNANCE_EXIT: votos insuficientes ({valid_votes}/{required})")
                    return False
                # Ejecutar exit — eliminar del registry (keystore perdido, stake quemado)
                registry = self.validator_registry
                # Buscar por hash completo o prefijo
                target_full = next((k for k in registry.validators if k.startswith(target)), target)
                if target_full in registry.validators:
                    del registry.validators[target_full]
                    registry.slashed.add(target_full)
                    print(f"[State] GOVERNANCE_EXIT: {target_full[:8]} expulsado con {valid_votes}/{required} votos ✓")
                else:
                    print(f"[State] GOVERNANCE_EXIT: {target[:8]} no encontrado en registry")
                return True

            vm_success = self.vm.execute(tx_id, sender_hash, payload)
            if not vm_success:
                return False


        # 2. Procesar transacción financiera
        if not sender_m3:  # Coinbase
            self.storage.credit(receiver_hash, amount)
            return True

        sender_balance = self.storage.get_balance(sender_hash)
        total_deduction = amount + fee
        if sender_balance < total_deduction:
            return False

        self.storage.transfer(sender_hash, receiver_hash, amount, fee)
        return True
