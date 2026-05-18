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
relayer.py — Oráculo Bidireccional Metriplex ↔ Ethereum (Sepolia)
=================================================================
Implementa el puente cross-chain en ambas direcciones:

  FLUJO 1 — Nativo → Ethereum (MINT):
    El usuario envía MPX nativos a la dirección de la Bóveda.
    El relayer detecta la TX, llama mint() en el contrato ERC-20.

  FLUJO 2 — Ethereum → Nativo (RELEASE):
    El usuario llama burnForNative(amount, nativeRecipient) en Ethereum.
    El relayer detecta el evento BridgeBurn y libera MPX desde la Bóveda.

Requisitos:
  pip install web3 requests cryptography

Configuración necesaria antes de correr:
  - VAULT_KEYSTORE_PATH: ruta al keystore cifrado de la Bóveda
  - VAULT_KEYSTORE_PASSWORD: contraseña (idealmente desde variable de entorno)
  - RELAYER_EVM_PRIV_KEY: clave privada EVM del relayer (la que desplegó el contrato)
"""

import asyncio
import json
import os
import sys
import hashlib
import time

import requests

# ── DEDUPLICACIÓN DE EVENTOS ─────────────────────────────────────────────────
import sqlite3 as _sqlite3
_RELAYER_STATE_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'relayer_state.db')

def _init_relayer_db():
    conn = _sqlite3.connect(_RELAYER_STATE_DB)
    conn.execute(
        'CREATE TABLE IF NOT EXISTS processed_burns '
        '(burn_tx_hash TEXT PRIMARY KEY, processed_at INTEGER)'
    )
    conn.commit()
    conn.close()
    print(f'[Relayer] Estado de dedup cargado: {_RELAYER_STATE_DB}')

def _is_processed(burn_tx_hash: str) -> bool:
    conn = _sqlite3.connect(_RELAYER_STATE_DB)
    row = conn.execute(
        'SELECT 1 FROM processed_burns WHERE burn_tx_hash=?', (burn_tx_hash,)
    ).fetchone()
    conn.close()
    return row is not None

def _mark_processed(burn_tx_hash: str):
    import time as _time
    conn = _sqlite3.connect(_RELAYER_STATE_DB)
    conn.execute(
        'INSERT OR IGNORE INTO processed_burns(burn_tx_hash, processed_at) VALUES(?,?)',
        (burn_tx_hash, int(_time.time()))
    )
    conn.commit()
    conn.close()
# ─────────────────────────────────────────────────────────────────────────────
from web3 import Web3

# ──────────────────────────────────────────────────────────────────────────────
#  CONFIGURACIÓN
# ──────────────────────────────────────────────────────────────────────────────

# Dirección del contrato WrappedMetriplex en Sepolia
CONTRACT_ADDRESS = "0x22D3f414438556d1B071cCfE52513d4d829400fd"

# Clave privada EVM del relayer (dueño del contrato, autorizado a llamar mint())
# En producción: leer desde variable de entorno, nunca hardcodeado
# IMPORTANTE: configura esta variable en tu entorno, nunca hardcodeada
# Ejecutar: export RELAYER_EVM_KEY="tu_clave_privada"
# O crear un archivo .env basado en .env.example
RELAYER_EVM_PRIV_KEY = os.environ.get("RELAYER_EVM_KEY", "")
if not RELAYER_EVM_PRIV_KEY:
    raise EnvironmentError(
        "[Relayer] RELAYER_EVM_KEY no configurada. "
        "Copia .env.example como .env y rellena tu clave privada EVM. "
        "Ejecuta: export RELAYER_EVM_KEY='tu_clave'"
    )

# Nodo local Metriplex
wMXP_NODE_URL = os.environ.get("MXP_NODE_URL", "http://localhost:8000")

# Keystore de la Bóveda (la cuenta nativa que custodia los fondos bloqueados)
VAULT_KEYSTORE_PATH = os.environ.get("VAULT_KEYSTORE", "vault_keystore.json")
VAULT_KEYSTORE_PASSWORD = os.environ.get("VAULT_PASSWORD", "")

# Tensor M3 de la Bóveda (igual al almacenado en el relayer anterior)
VAULT_MPX_ADDRESS = [[[-767737, -640365, 3959581, 106598], [-640364, 3512988, 3191937, 975426], [3959581, 3191937, 1345000, 4022728], [106598, 975426, 4022728, 35378]], [[-640364, 3512988, 3191937, 975426], [3512988, -3101786, 1688013, -2615231], [3191937, 1688013, 1823774, -3989328], [975426, -2615231, -3989328, -2562126]], [[3959581, 3191937, 1345000, 4022728], [3191937, 1688013, 1823774, -3989328], [1345000, 1823774, 2942833, -550010], [4022728, -3989328, -550010, -1757593]], [[106598, 975426, 4022728, 35378], [975426, -2615231, -3989328, -2562126], [4022728, -3989328, -550010, -1757593], [1847787, -3641039, 4171453, -324450]]]

# Proveedor Web3 (Sepolia vía Brave o cualquier RPC público)
WEB3_PROVIDER_URL = os.environ.get(
    "WEB3_RPC",
    "https://mainnet.base.org"
)

# ABI mínimo del contrato
CONTRACT_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
        ],
        "name": "mint",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "from", "type": "address"},
            {"indexed": False, "internalType": "string", "name": "nativeRecipient", "type": "string"},
            {"indexed": False, "internalType": "uint256", "name": "amount", "type": "uint256"},
        ],
        "name": "BridgeBurn",
        "type": "event",
    },
]

# ──────────────────────────────────────────────────────────────────────────────
#  INICIALIZACIÓN WEB3
# ──────────────────────────────────────────────────────────────────────────────

w3 = Web3(Web3.HTTPProvider(WEB3_PROVIDER_URL))
contract = w3.eth.contract(
    address=Web3.to_checksum_address(CONTRACT_ADDRESS), abi=CONTRACT_ABI
)
relayer_account = w3.eth.account.from_key(RELAYER_EVM_PRIV_KEY)

# ──────────────────────────────────────────────────────────────────────────────
#  CARGA DEL KEYSTORE DE LA BÓVEDA
# ──────────────────────────────────────────────────────────────────────────────

def load_vault() -> tuple:
    """
    Carga la clave privada de la Bóveda desde el keystore cifrado.
    Retorna (vault_priv, vault_pub, vault_params, vault_attractor).
    Si el keystore no existe, genera uno nuevo y lo guarda.
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from crypto.keystore import load_keystore, save_keystore
    from core.verifier import calibrate, CriterionParams

    if not os.path.exists(VAULT_KEYSTORE_PATH):
        print(f"[Bóveda] No se encontró keystore en '{VAULT_KEYSTORE_PATH}'.")
        print("[Bóveda] Generando identidad fractal de la Bóveda...")

        from crypto.keys import generate_private_key, derive_public_key_with_attractor
        vault_priv = generate_private_key()
        vault_pub, vault_att = derive_public_key_with_attractor(vault_priv)
        n_maps = len(vault_priv["A"])
        vault_params = calibrate(vault_att, vault_priv["A"], vault_priv["b"], n_maps, n_samples=40)
        params_dict = vault_params.to_dict()

        pwd = VAULT_KEYSTORE_PASSWORD or input("[Bóveda] Contraseña para proteger el keystore: ")
        save_keystore(pwd, vault_priv, vault_pub, params_dict, vault_att, VAULT_KEYSTORE_PATH)
        print(f"[Bóveda] Keystore guardado en '{VAULT_KEYSTORE_PATH}'.")
        print("[!] Actualiza VAULT_MPX_ADDRESS en relayer.py con este nuevo tensor M3.")
        return vault_priv, vault_pub, vault_params, vault_att

    pwd = VAULT_KEYSTORE_PASSWORD or input(f"[Bóveda] Contraseña para '{VAULT_KEYSTORE_PATH}': ")
    vault_priv, vault_pub, params_dict, vault_att = load_keystore(pwd, VAULT_KEYSTORE_PATH)

    from core.verifier import CriterionParams
    vault_params = (
        CriterionParams(**params_dict) if isinstance(params_dict, dict) else params_dict
    )
    print("[Bóveda] Keystore cargado correctamente.")
    return vault_priv, vault_pub, vault_params, vault_att


# ──────────────────────────────────────────────────────────────────────────────
#  FLUJO 1: NATIVO → ETHEREUM (MINT)
# ──────────────────────────────────────────────────────────────────────────────

async def monitor_native_chain():
    """
    Monitorea el nodo MPX buscando depósitos a la Bóveda.
    Cuando detecta una TX con payload.target_eth_address, ejecuta mint() en Ethereum.
    """
    print("[Relayer] Monitoreando depósitos en la red nativa MPX...")
    last_processed_block = -1

    while True:
        try:
            response = requests.get(f"{wMXP_NODE_URL}/blocks", timeout=5)
            blocks = response.json()

            for block in blocks:
                if block["index"] <= last_processed_block:
                    continue

                for tx in block["transactions"]:
                    # Detectar TX hacia la dirección de la Bóveda con target_eth_address
                    if tx.get("receiver_m3") == VAULT_MPX_ADDRESS:
                        payload = tx.get("payload", {})
                        eth_target = payload.get("target_eth_address", "")
                        amount = tx.get("amount", 0)

                        if eth_target and w3.is_address(eth_target) and amount > 0:
                            print(f"\n[!] Depósito detectado en bloque {block['index']}")
                            print(f"    Monto:   {amount} MPX (raw)")
                            print(f"    Destino: {eth_target}")
                            execute_eth_mint(eth_target, amount)

                last_processed_block = block["index"]

        except requests.exceptions.ConnectionError:
            print("[Relayer] Nodo local no disponible. Reintentando...")
        except Exception as e:
            print(f"[Error Nativo] {type(e).__name__}: {e}")

        await asyncio.sleep(5)


def execute_eth_mint(target_address: str, amount: int):
    """Ejecuta mint() en el Smart Contract de Ethereum."""
    try:
        nonce = w3.eth.get_transaction_count(relayer_account.address)
        tx = contract.functions.mint(
            Web3.to_checksum_address(target_address), amount
        ).build_transaction({
            "chainId": w3.eth.chain_id,
            "gas": 200_000,
            "gasPrice": w3.eth.gas_price,
            "nonce": nonce,
        })
        signed_tx = w3.eth.account.sign_transaction(tx, private_key=RELAYER_EVM_PRIV_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        print(f"[>] Mint ejecutado en Ethereum. TX Hash: {w3.to_hex(tx_hash)}")
    except Exception as e:
        print(f"[Error Mint] {type(e).__name__}: {e}")


# ──────────────────────────────────────────────────────────────────────────────
#  FLUJO 2: ETHEREUM → NATIVO (BURN / RELEASE)
# ──────────────────────────────────────────────────────────────────────────────

async def monitor_eth_events(vault_priv, vault_pub, vault_params, vault_att):
    """
    Escucha el evento BridgeBurn en el contrato ERC-20.
    Cuando se detecta, ejecuta una TX ZK desde la Bóveda hacia el usuario nativo.

    El campo nativeRecipient del evento debe contener el tensor M3 del usuario
    serializado como JSON (lo que produce wallet_cli.py al exportar la llave pública).
    """
    print("[Relayer] Monitoreando evento BridgeBurn en Ethereum...")
    last_processed_eth_block = w3.eth.block_number - 250  # lookback 250 blocks on start

    while True:
        try:
            current_block = w3.eth.block_number

            if current_block > last_processed_eth_block:
                events = contract.events.BridgeBurn().get_logs(
                    from_block=last_processed_eth_block + 1,
                    to_block=current_block,
                )

                for event in events:
                    eth_sender       = event["args"]["from"]
                    native_recipient = event["args"]["nativeRecipient"]
                    amount_wei       = event["args"]["amount"]
                    # Convertir wei (18 decimals) a CAF scale (2^30)
                    _scale = 1073741824  # 2^30
                    amount           = int(amount_wei * _scale // (10**18))
                    burn_tx_hash     = w3.to_hex(event["transactionHash"])

                    print(f"\n[!] BridgeBurn detectado:")
                    print(f"    Quemador EVM: {eth_sender}")
                    print(f"    Monto:        {amount} wMPX")
                    print(f"    TX Ethereum:  {burn_tx_hash}")

                    if _is_processed(burn_tx_hash):
                        print(f'[Relayer] Dedup: TX ya procesada {burn_tx_hash[:16]}...')
                        continue
                    execute_native_release(
                        native_recipient, amount, burn_tx_hash,
                        vault_priv, vault_pub, vault_params, vault_att
                    )
                    _mark_processed(burn_tx_hash)

                last_processed_eth_block = current_block

        except Exception as e:
            print(f"[Error EVM] {type(e).__name__}: {e}")

        await asyncio.sleep(10)


def execute_native_release(
    native_recipient_json: str,
    amount: int,
    burn_tx_hash: str,
    vault_priv:   dict,
    vault_pub:    list,
    vault_params,
    vault_att:    list,
):
    """
    Libera MPX nativos desde la Bóveda hacia el usuario.

    Parámetros:
        native_recipient_json: tensor M3 del usuario serializado como JSON string.
                               El usuario obtiene este string con:
                               json.dumps(pub_m3) desde su wallet.
        amount:               monto en unidades raw (igual al quemado en Ethereum).
        burn_tx_hash:         hash de la TX de quema en Ethereum (para el payload/auditoría).
        vault_priv/pub/...    credenciales de la Bóveda (cargadas al inicio).
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from core.arithmetic import SCALE_FACTOR
    from core.verifier import CriterionParams
    if isinstance(vault_params, dict):
        vault_params = CriterionParams(**vault_params)
    from crypto.signatures import sign_transaction

    try:
        # 1. Parsear el tensor M3 del receptor
        try:
            receiver_m3 = json.loads(native_recipient_json)
        except (json.JSONDecodeError, ValueError):
            print(f"[Release] ERROR: nativeRecipient no es un JSON válido.")
            print(f"          El usuario debe pasar json.dumps(pub_m3) en burnForNative().")
            return

        if not isinstance(receiver_m3, list):
            print("[Release] ERROR: nativeRecipient no es una lista (tensor M3 inválido).")
            return

        # 2. Verificar saldo de la Bóveda antes de intentar la TX
        try:
            balance_res = requests.get(
                f"{wMXP_NODE_URL}/balance",
                params={"tensor": json.dumps(VAULT_MPX_ADDRESS)},
                timeout=5
            )
            # Consulta directa usando el hash del tensor
            import hashlib
            vault_hash = hashlib.sha256(
                json.dumps(VAULT_MPX_ADDRESS, sort_keys=True, separators=(',',':')).encode()
            ).hexdigest()
            # Consultar DB directamente para evitar WAL cache del nodo
            import sqlite3 as _sqlite3
            _db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "node_data_8000.db")
            try:
                _conn = _sqlite3.connect(_db_path, timeout=5.0)
                _cur = _conn.cursor()
                _cur.execute("SELECT balance FROM balances WHERE tensor_hash=?", (vault_hash,))
                _row = _cur.fetchone()
                vault_balance = _row[0] if _row else 0
                _conn.close()
            except Exception:
                bal_res = requests.get(f"{wMXP_NODE_URL}/balance/{vault_hash}", timeout=5)
                vault_balance = bal_res.json().get("balance_raw", 0)

            fee = 1 * SCALE_FACTOR
            if vault_balance < amount + fee:
                print(f"[Release] ERROR: Saldo insuficiente en la Bóveda.")
                print(f"          Bóveda: {vault_balance}  Requerido: {amount + fee}")
                return
        except Exception as e:
            print(f"[Release] Advertencia: No se pudo verificar saldo ({e}). Continuando...")

        # 3. Construir el payload de la TX
        fee = 1 * SCALE_FACTOR
        tx_payload_dict = {
            "sender_m3":   vault_pub,
            "receiver_m3": receiver_m3,
            "amount":      amount,
            "fee":         fee,
            "payload": {
                "bridge":    "ETH_TO_NATIVE",
                "burn_tx":   burn_tx_hash,    # auditoría: hash de la quema en ETH
                "timestamp": int(time.time()),
            },
        }

        # 4. Firmar con la clave privada de la Bóveda (genera proof ZK)
        print("[Release] Firmando TX ZK desde la Bóveda...")
        sig = sign_transaction(
            vault_priv,
            tx_payload_dict,
            vault_pub,
            criterion_params=vault_params,
            attractor=vault_att,
        )

        # 5. Enviar la TX al nodo local
        tx_request = {
            "sender_m3":    vault_pub,
            "receiver_m3":  receiver_m3,
            "amount":       amount,
            "fee":          fee,
            "signature_data": sig,
            "payload": tx_payload_dict["payload"],
        }

        print("[Release] Enviando TX al nodo Metriplex...")
        response = requests.post(
            f"{wMXP_NODE_URL}/transaction",
            json=tx_request,
            timeout=30,
        )

        if response.status_code == 200:
            tx_id = response.json().get("tx_id", "?")
            print(f"[✓] Release exitoso.")
            print(f"    TX nativa: {tx_id}")
            print(f"    Monto liberado: {amount / SCALE_FACTOR:.4f} wMXP")
        else:
            print(f"[Release] ERROR: El nodo rechazó la TX.")
            print(f"          Código: {response.status_code}")
            print(f"          Detalle: {response.text[:300]}")

    except requests.exceptions.ConnectionError:
        print("[Release] ERROR: No se puede conectar al nodo local.")
    except Exception as e:
        import traceback
        print(f"[Release] Excepción inesperada: {type(e).__name__}: {e}")
        traceback.print_exc()


# ──────────────────────────────────────────────────────────────────────────────
#  ORQUESTADOR
# ──────────────────────────────────────────────────────────────────────────────

async def main():
    print("=" * 55)
    print(" RELAYER METRIPLEX ↔ ETHEREUM")
    print("=" * 55)
    print(f" Contrato EVM:  {CONTRACT_ADDRESS}")
    print(f" Nodo nativo:   {wMXP_NODE_URL}")
    print(f" Relayer EVM:   {relayer_account.address}")
    _init_relayer_db()
    print("=" * 55)

    # Verificar conexión con el nodo local
    try:
        res = requests.get(f"{wMXP_NODE_URL}/info", timeout=5)
        info = res.json()
        print(f"[✓] Nodo Metriplex: {info.get('chain_length', '?')} bloques")
    except Exception:
        print("[!] Advertencia: No se puede conectar al nodo local en este momento.")
        print("    El relayer esperará y reintentará en los ciclos de monitoreo.")

    # Verificar conexión Web3
    if w3.is_connected():
        print(f"[✓] Ethereum Sepolia: conectado (bloque #{w3.eth.block_number})")
    else:
        print("[!] Advertencia: Sin conexión a Ethereum. El flujo 1 no funcionará.")

    print()

    # Cargar el keystore de la Bóveda para el flujo 2
    vault_priv, vault_pub, vault_params, vault_att = load_vault()
    print()

    # Ejecutar ambos monitores en paralelo
    await asyncio.gather(
        monitor_native_chain(),
        monitor_eth_events(vault_priv, vault_pub, vault_params, vault_att),
    )


if __name__ == "__main__":
    # Instrucciones rápidas
    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        print(__doc__)
        print()
        print("Variables de entorno:")
        print("  RELAYER_EVM_KEY   Clave privada EVM del relayer (32 bytes hex)")
        print("  VAULT_KEYSTORE    Ruta al keystore de la Bóveda [vault_keystore.json]")
        print("  VAULT_PASSWORD    Contraseña del keystore (o se pedirá interactivamente)")
        print("  MXP_NODE_URL      URL del nodo Metriplex [http://localhost:8000]")
        print("  WEB3_RPC          Proveedor RPC de Ethereum Sepolia")
        print()
        print("Ejemplo:")
        print("  VAULT_PASSWORD=miclave python relayer.py")
        sys.exit(0)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[!] Relayer detenido.")
