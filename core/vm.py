# SPDX-License-Identifier: BUSL-1.1
#
# Metriplex Cryptographic Core
# Copyright (c) 2025-2026 NTellezM (Nelson Tellez)
#
# This file is part of the Metriplex Cryptographic Core, licensed under
# the Business Source License 1.1 (BUSL-1.1).
#
# Non-production use (research, education, personal projects) is permitted.
# Production use requires a commercial license until 2027-05-09, after which
# this file is available under the MIT License.
#
# Contact: metriplexmpx@gmail.com
# License: See LICENSE-CORE in the repository root
#
"""
Máquina Virtual del Protocolo CAF (CAF-VM).
Procesa la lógica de los contratos inteligentes alterando el estado de la red.
"""

from blockchain.storage import Storage
import json

class CAFVirtualMachine:
    def __init__(self, storage: Storage):
        self.storage = storage

    def execute(self, tx_id: str, sender_hash: str, payload: dict) -> bool:
        """
        Interpreta y ejecuta el payload de una transacción.
        Retorna True si la ejecución es válida, False si el contrato falla.
        """
        if not payload:
            return True # Transacción financiera estándar

        try:
            op_code = payload.get("op")
            
            # OP_DEPLOY: Inicializa un nuevo espacio de almacenamiento
            if op_code == "DEPLOY":
                # La dirección del contrato se deriva del ID de la transacción que lo creó
                contract_address = f"caf_cx_{tx_id[:16]}"
                init_data = payload.get("init_data", {})
                
                # Guardar creador y datos iniciales
                self.storage.set_contract_state(contract_address, "owner", sender_hash)
                for k, v in init_data.items():
                    self.storage.set_contract_state(contract_address, str(k), str(v))
                
                print(f"[VM] Contrato desplegado: {contract_address}")
                return True

            # OP_INVOKE: Modifica el estado de un contrato existente
            elif op_code == "INVOKE":
                contract_address = payload.get("contract_address")
                method = payload.get("method")
                args = payload.get("args", {})

                if not contract_address or not method:
                    return False

                # Lógica básica de acceso: solo el owner puede escribir (prototipo)
                owner = self.storage.get_contract_state(contract_address, "owner")
                if owner != sender_hash:
                    print(f"[VM] Error: Ejecución denegada. El emisor no es el propietario.")
                    return False

                if method == "SET_DATA":
                    for k, v in args.items():
                        self.storage.set_contract_state(contract_address, str(k), str(v))
                    print(f"[VM] Estado actualizado en {contract_address}")
                    return True

            # Payload sin op_code reconocido — datos de auditoría, no contrato
            return True
            
        except Exception as e:
            print(f"[VM] Excepción crítica durante ejecución: {e}")
            return False