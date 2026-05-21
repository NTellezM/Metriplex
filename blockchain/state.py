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
    def __init__(self, storage: Storage):
        self.storage = storage
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

            # VALIDATOR_SLASH — stake quemado
            if op == "VALIDATOR_SLASH":
                print(f"[State] VALIDATOR_SLASH: stake de {payload.get('target_m3_hash','?')[:8]} quemado.")
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
