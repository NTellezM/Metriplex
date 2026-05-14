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
Cliente CLI de Billetera Interactiva para el protocolo CAF.
Soporta cifrado en disco, exportación de llaves públicas y transacciones instantáneas.
"""

import hashlib
import json
import os
from getpass import getpass

import requests

from core.arithmetic import SCALE_FACTOR
from core.verifier import CriterionParams, calibrate
from crypto.keys import derive_public_key_with_attractor, generate_private_key
from crypto.keystore import load_keystore, save_keystore
from crypto.signatures import sign_transaction

NODE_URL = "http://localhost:8001"


def get_tensor_hash(m3_tensor: list) -> str:
    m3_str = json.dumps(m3_tensor, sort_keys=True).encode()
    return hashlib.sha256(m3_str).hexdigest()


def create_wallet():
    filename = input("Nombre del archivo keystore (ej. mi_wallet.json): ")
    if os.path.exists(filename):
        print("[!] El archivo ya existe.")
        return

    pwd = getpass("Crea una contraseña segura: ")
    pwd2 = getpass("Confirma la contraseña: ")
    if pwd != pwd2:
        print("[!] Las contraseñas no coinciden.")
        return

    print(
        "\n[*] Generando dinámica fractal y calibrando atractor (Esto tomará unos segundos)..."
    )
    priv = generate_private_key()
    pub, attractor = derive_public_key_with_attractor(priv)
    n_maps = len(priv["A"])
    params = calibrate(attractor, priv["A"], priv["b"], n_maps)

    params_dict = params.to_dict() if hasattr(params, "to_dict") else vars(params)
    save_keystore(pwd, priv, pub, params_dict, attractor, filename)


def open_wallet():
    filename = input("Archivo keystore a cargar: ")
    pwd = getpass("Contraseña: ")

    try:
        priv, pub, params, attractor = load_keystore(pwd, filename)
        wallet_session(priv, pub, params, attractor)
    except Exception as e:
        print(f"[!] Error al abrir la billetera: {e}")


def wallet_session(priv, pub, params_dict, attractor):
    address = get_tensor_hash(pub)
    params_obj = (
        CriterionParams(**params_dict) if isinstance(params_dict, dict) else params_dict
    )

    while True:
        print("\n" + "=" * 50)
        print(f"💼 Billetera Activa: {address[:16]}...{address[-8:]}")
        print("=" * 50)
        print("1. Consultar Saldo")
        print("2. Exportar Llave Pública (Para recibir fondos)")
        print("3. Solicitar Fondos (Faucet)")
        print("4. Enviar wMXP")
        print("5. Cerrar Sesión")
        op = input("\nSelecciona una opción: ")

        if op == "1":
            try:
                res = requests.get(f"{NODE_URL}/balance/{address}").json()
                # La API devuelve 'balance_caf' (ya dividido por SCALE_FACTOR)
                bal = res.get("balance_caf", res.get("balance_raw", 0) / SCALE_FACTOR)
                print(f"\n💰 Saldo Actual: {round(bal, 6)} wMXP")
            except Exception as e:
                print(f"[!] Error de red: {e}")

        elif op == "2":
            out_file = input(
                "Nombre del archivo para exportar (ej. pub_destino.json): "
            )

            # PREVENCIÓN: Evitar sobreescribir un archivo Keystore existente
            if os.path.exists(out_file):
                try:
                    with open(out_file, "r") as f:
                        data = json.load(f)
                        if isinstance(data, dict) and "encrypted_private_key" in data:
                            print(
                                "[!] ACCIÓN BLOQUEADA: Estás intentando sobreescribir un archivo Keystore cifrado."
                            )
                            continue
                except Exception:
                    pass  # Si no es un JSON válido, procedemos a sobreescribirlo si el usuario quiere

            with open(out_file, "w") as f:
                json.dump(pub, f)
            print(f"[*] Llave pública exportada exitosamente a {out_file}")

        elif op == "3":
            try:
                print("[*] Solicitando fondos al contrato Faucet...")
                res = requests.post(f"{NODE_URL}/faucet", json=pub).json()
                print(f"[*] Respuesta: {res.get('message', res)}")
            except Exception as e:
                print(f"[!] Error de red: {e}")

        elif op == "4":
            dest_file = input(
                "Ruta del archivo de la llave pública destino (ej. pub_destino.json): "
            )
            try:
                with open(dest_file, "r") as f:
                    receiver_data = json.load(f)

                    # Inteligencia de extracción: Si es un Keystore, extraer solo public_m3
                    if isinstance(receiver_data, dict) and "public_m3" in receiver_data:
                        receiver_pub = receiver_data["public_m3"]
                    elif isinstance(receiver_data, list):
                        receiver_pub = receiver_data
                    else:
                        print("[!] Formato de archivo destino no reconocido.")
                        continue
            except Exception:
                print("[!] No se pudo leer el archivo destino.")
                continue

            amount_str = input("Monto a enviar (wMXP): ")
            fee_str = input("Comisión de red (wMXP) [Default 1]: ") or "1"

            # --- NUEVO CÓDIGO PARA EL PUENTE ---
            eth_address = input(
                "Dirección Ethereum destino (Deja vacío si no es para el puente): "
            ).strip()
            custom_payload = {}
            if eth_address:
                custom_payload["target_eth_address"] = eth_address
            # -----------------------------------

            try:
                amount = int(float(amount_str) * SCALE_FACTOR)
                fee = int(float(fee_str) * SCALE_FACTOR)

                payload_dict = {
                    "sender_m3": pub,
                    "receiver_m3": receiver_pub,
                    "amount": amount,
                    "fee": fee,
                    "payload": custom_payload,  # Usamos el payload dinámico
                }

                print("[*] Firmando transacción (Instántaneo usando caché)...")
                sig = sign_transaction(
                    priv,
                    payload_dict,
                    pub,
                    criterion_params=params_obj,
                    attractor=attractor,
                )

                tx_payload = {
                    "sender_m3": pub,
                    "receiver_m3": receiver_pub,
                    "amount": amount,
                    "fee": fee,
                    "signature_data": sig,
                    "payload": custom_payload,  # Y lo enviamos en la TX
                }

                res = requests.post(f"{NODE_URL}/transaction", json=tx_payload)
                if res.status_code == 200:
                    print(
                        f"\n[✓] Transacción enviada al Mempool. ID: {res.json().get('tx_id')}"
                    )
                else:
                    print(f"\n[!] Rechazo: {res.text}")
            except Exception as e:
                print(f"[!] Error en la emisión: {e}")

        elif op == "5":
            break


if __name__ == "__main__":
    while True:
        print("\n" + "-" * 40)
        print(" 🛡️  wMXP WALLET CLI")
        print("-" * 40)
        print("1. Crear nueva Billetera")
        print("2. Cargar Billetera existente")
        print("3. Salir del programa")
        op = input("\nOpción: ")

        if op == "1":
            create_wallet()
        elif op == "2":
            open_wallet()
        elif op == "3":
            break
