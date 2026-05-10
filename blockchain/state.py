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
        tensor_str = json.dumps(m3_tensor, sort_keys=True).encode()
        return hashlib.sha256(tensor_str).hexdigest()

    def get_balance(self, m3_tensor: list) -> int:
        tensor_hash = self._hash_tensor(m3_tensor)
        return self.storage.get_balance(tensor_hash)

    def mint(self, m3_tensor: list, amount: int):
        tensor_hash = self._hash_tensor(m3_tensor)
        current_balance = self.storage.get_balance(tensor_hash)
        self.storage.update_balance(tensor_hash, current_balance + amount)

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
            vm_success = self.vm.execute(tx_id, sender_hash, payload)
            if not vm_success:
                return False  # Si el contrato falla, la transacción se revierte por completo

        # 2. Procesar transacción financiera
        if not sender_m3:  # Coinbase
            receiver_balance = self.storage.get_balance(receiver_hash)
            self.storage.update_balance(receiver_hash, receiver_balance + amount)
            return True

        sender_balance = self.storage.get_balance(sender_hash)
        total_deduction = amount + fee
        if sender_balance < total_deduction:
            return False

        self.storage.update_balance(sender_hash, sender_balance - total_deduction)
        receiver_balance = self.storage.get_balance(receiver_hash)
        self.storage.update_balance(receiver_hash, receiver_balance + amount)
        return True
