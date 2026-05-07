"""
Cliente de línea de comandos para Contratos Inteligentes CAF.
Demuestra el despliegue e invocación de lógica en la CAF-VM.
"""

import hashlib
import json
import time
import requests
from core.arithmetic import SCALE_FACTOR
from crypto.keys import derive_public_key, generate_private_key
from crypto.signatures import sign_transaction

NODE_URL = "http://localhost:8000"

def get_tensor_hash(m3_tensor: list) -> str:
    m3_str = json.dumps(m3_tensor, sort_keys=True).encode()
    return hashlib.sha256(m3_str).hexdigest()

def main():
    print("--- INICIANDO PRUEBA DE SMART CONTRACTS CAF ---")

    # 1. Crear identidad del desarrollador
    print("\n1. Creando Billetera del Desarrollador...")
    pk_dev, pub_dev = generate_private_key(), None
    pub_dev = derive_public_key(pk_dev)

    # 2. Solicitar fondos operativos
    print("\n2. Solicitando fondos (Faucet)...")
    requests.post(f"{NODE_URL}/faucet", json=pub_dev)
    print("   [!] Esperando 12s para confirmación...")
    time.sleep(12)

    # 3. Construir transacción de Despliegue (DEPLOY)
    print("\n3. Desplegando Contrato de Registro (DEPLOY)...")
    payload_deploy = {
        "op": "DEPLOY",
        "init_data": {
            "name": "CAF_Data_Matrix",
            "version": "1.0",
            "description": "Contrato de almacenamiento topológico"
        }
    }
    
    tx_deploy = {
        "sender_m3": pub_dev,
        "receiver_m3": [],  # Los contratos no tienen receptor humano
        "amount": 10 * SCALE_FACTOR,  # Costo ficticio de gas/despliegue
        "payload": payload_deploy
    }
    
    sig_deploy = sign_transaction(pk_dev, tx_deploy, pub_dev)
    tx_deploy["signature_data"] = sig_deploy

    res_deploy = requests.post(f"{NODE_URL}/transaction", json=tx_deploy)
    tx_id = res_deploy.json().get('tx_id')
    print(f"   [ÉXITO] Transacción enviada. TX ID: {tx_id[:16]}...")
    
    # Calcular la dirección predecible del contrato
    contract_address = f"caf_cx_{tx_id[:16]}"
    print(f"   [VM] Dirección del Contrato: {contract_address}")

    print("   [!] Esperando 12s para que la VM lo ejecute...")
    time.sleep(12)

    # 4. Modificar el estado del contrato (INVOKE)
    print("\n4. Escribiendo datos en el Contrato (INVOKE)...")
    payload_invoke = {
        "op": "INVOKE",
        "contract_address": contract_address,
        "method": "SET_DATA",
        "args": {
            "status": "Activo",
            "sensor_data": "Valores M3 Sincronizados",
            "phase": "Fase 2 Completada"
        }
    }

    tx_invoke = {
        "sender_m3": pub_dev,
        "receiver_m3": [],
        "amount": 2 * SCALE_FACTOR,  # Costo de ejecución
        "payload": payload_invoke
    }

    sig_invoke = sign_transaction(pk_dev, tx_invoke, pub_dev)
    tx_invoke["signature_data"] = sig_invoke

    res_invoke = requests.post(f"{NODE_URL}/transaction", json=tx_invoke)
    print(f"   [ÉXITO] Invocación enviada. TX ID: {res_invoke.json().get('tx_id')[:16]}...")

    print("   [!] Esperando 12s para alteración de estado...")
    time.sleep(12)
    print("\n--- PRUEBA FINALIZADA ---")

if __name__ == "__main__":
    main()