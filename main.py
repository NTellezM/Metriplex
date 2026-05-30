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
Punto de entrada principal para el nodo del Protocolo CAF.
Soporta configuración de puertos por CLI y roles de red (Validador/Observador).
"""

import argparse
import asyncio
import sys
import socket

import signal
import uvicorn

from api.server import create_api_app
from blockchain.chain import Blockchain
from blockchain.storage import Storage
from network.mempool import Mempool
from network.miner import AutoMiner
from network.p2p import CAFNode


async def main():
    parser = argparse.ArgumentParser(description="Nodo del Protocolo CAF")
    parser.add_argument(
        "--api-port", type=int, default=8000, help="Puerto para la API REST"
    )
    parser.add_argument(
        "--p2p-port", type=int, default=65432, help="Puerto para la red P2P TCP"
    )
    parser.add_argument(
        "--peer", type=str, default=None, help="IP:Puerto de un nodo conocido"
    )
    parser.add_argument("--public-ip", type=str, default=None, help="IP publica de este nodo")
    parser.add_argument(
        "--no-miner",
        action="store_true",
        help="Inicia el nodo en modo Solo-Observador (Full Node)",
    )
    parser.add_argument(
        "--miner-wallet",
        type=str,
        default=None,
        help="Ruta al archivo .json de llave pública del minero para recibir recompensas",
    )
    args = parser.parse_args()

    P2P_HOST = "0.0.0.0"
    API_HOST = "0.0.0.0"
    import os as _os
    _data_dir = _os.environ.get("NODE_DATA_DIR", ".")
    db_filename = _os.path.join(_data_dir, f"node_data_{args.api_port}.db")

    rol_nodo = "OBSERVADOR (Full Node)" if args.no_miner else "VALIDADOR (Minero)"

    # --- Auto-detección de IP pública ---
    BOOTSTRAP_PEERS = [
        "157.180.113.24:65432",  # node-0 genesis
        "157.180.113.24:65433",  # NT-vps
        "152.173.186.164:65434", # node-2 LOQ-15
        "152.173.186.164:65435", # NT-laptop Y520
    ]

    if args.public_ip:
        public_ip = args.public_ip
        ip_source = "manual"
    else:
        try:
            import urllib.request
            public_ip = urllib.request.urlopen(
                "https://api.ipify.org", timeout=5
            ).read().decode().strip()
            ip_source = "auto-detectada"
        except Exception:
            public_ip = "127.0.0.1"
            ip_source = "fallback (sin internet)"

    # --- Bootstrap peers — conectar a TODOS (malla completa) ---
    bootstrap_peers = [
        bp for bp in BOOTSTRAP_PEERS
        if bp.split(":")[1] != str(args.p2p_port)
        and bp != f"{public_ip}:{args.p2p_port}"
    ]
    if not args.peer and bootstrap_peers:
        args.peer = bootstrap_peers[0]
    # Guardar lista completa para agregar al p2p_node después de init
    args.all_peers = bootstrap_peers

    # --- Verificar alcanzabilidad del peer ---
    def check_peer(peer_str):
        try:
            host, port = peer_str.rsplit(":", 1)
            s = socket.create_connection((host, int(port)), timeout=3)
            s.close()
            return True
        except Exception:
            return False

    peer_status = "✓ alcanzable" if check_peer(args.peer) else "✗ no alcanzable"

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  METRIPLEX NODE STARTING")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  API port   : {args.api_port}")
    print(f"  P2P port   : {args.p2p_port}")
    print(f"  Public IP  : {public_ip}  ({ip_source})")
    print(f"  Modo       : {rol_nodo}")
    print(f"  Peer       : {args.peer}  {peer_status}")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    storage = Storage(db_filename)
    blockchain = Blockchain(storage)
    print(f"[✓] Cadena cargada ({len(blockchain.chain)} bloques en disco).")

    mempool = Mempool(blockchain)
    print("[✓] Mempool inicializado.")

    # --- Cargar geo_identity para GEO_HANDSHAKE ---
    geo_identity = None
    if args.miner_wallet:
        try:
            import json as _json
            from crypto.keystore import load_keystore
            import os
            _ks_raw = _json.load(open(args.miner_wallet))
            if 'encrypted_private_key' in _ks_raw:
                _pwd = os.environ.get("MINER_PASSWORD", "")
                if not _pwd:
                    import getpass
                    _pwd = getpass.getpass("[GEO] Password del keystore: ")
                _priv, _pub, _params, _att = load_keystore(_pwd, args.miner_wallet)
                geo_identity = {
                    "private_key": _priv,
                    "public_m3": _pub,
                    "criterion_params": _params,
                    "attractor": _att,
                }
            else:
                # Keystore sin cifrar — sin criterion_params
                geo_identity = {
                    "public_m3": _ks_raw.get("public_m3"),
                    "criterion_params": None,
                    "attractor": None,
                    "private_key": None,
                }
        except Exception as _e:
            print(f"[GEO] No se pudo cargar geo_identity: {_e}")

    p2p_node = CAFNode(
        host=P2P_HOST, port=args.p2p_port, blockchain=blockchain, mempool=mempool,
        host_public=public_ip, geo_identity=geo_identity
    )

    # Agregar TODOS los bootstrap peers — malla completa
    all_peers = getattr(args, 'all_peers', [args.peer] if args.peer else [])
    for bp in all_peers:
        if bp:
            p2p_node.peers.add(bp)
    if all_peers:
        print(f"[Red] Bootstrap peers: {len(all_peers)} nodos → {', '.join(all_peers)}")

    app = create_api_app(blockchain, mempool, p2p_node)
    config = uvicorn.Config(
        app, host=API_HOST, port=args.api_port, log_level="warning", access_log=False
    )
    api_server = uvicorn.Server(config)

    # Definir tareas asíncronas dinámicamente según el rol
    tasks = [p2p_node.start_server(), api_server.serve()]

    if not args.no_miner:
        miner_m3 = None
        if args.miner_wallet:
            try:
                import json
                with open(args.miner_wallet) as f:
                    ks = json.load(f)
                    miner_m3 = ks.get('public_m3', ks) if isinstance(ks, dict) else ks
                print(f"[✓] Billetera del minero cargada para recompensas automáticas.")
            except Exception as e:
                print(f"[!] No se pudo cargar la billetera del minero: {e}")

        miner = AutoMiner(
            blockchain=blockchain,
            mempool=mempool,
            p2p_node=p2p_node,
            block_time_seconds=60,
            miner_m3=miner_m3,
        )
        tasks.append(miner.start())
    # Auto-publicar endpoint actual al arrancar — resuelve IP dinámica
    async def auto_update_endpoint():
        """Espera sync y publica IP:puerto actual via VALIDATOR_UPDATE.
        Reutiliza geo_identity ya cargado en memoria — no necesita password."""
        await asyncio.sleep(45)
        if not geo_identity or not geo_identity.get("private_key"):
            # Keystore sin cifrar — cargar matrices directamente
            if args.miner_wallet and geo_identity:
                try:
                    import json as _j2
                    _ks2 = _j2.load(open(args.miner_wallet))
                    import numpy as _np
                    _matrices = _ks2.get("contraction_matrices") or _ks2.get("private_key")
                    if not _matrices:
                        return
                    geo_identity["private_key"] = [_np.array(m) for m in _matrices]
                    from core.dynamics import compute_attractor
                    from core.verifier import CriterionParams as _CP
                    geo_identity["attractor"] = compute_attractor(geo_identity["private_key"])
                    geo_identity["criterion_params"] = _CP.from_attractor(geo_identity["attractor"])
                except Exception as _e2:
                    print(f"[FVR] No se pudo cargar keystore sin cifrar: {_e2}")
                    return
            else:
                return
        try:
            import json as _json, hashlib as _hl
            from blockchain.block import Transaction
            from crypto.zkp import ZKEngine
            from core.verifier import CriterionParams

            m3     = geo_identity["public_m3"]
            priv   = geo_identity["private_key"]
            params = geo_identity["criterion_params"]
            att    = geo_identity["attractor"]

            new_endpoint = f"{public_ip}:{args.p2p_port}"
            m3_hash = _hl.sha256(
                _json.dumps(m3, sort_keys=True, separators=(',',':')).encode()
            ).hexdigest()

            current = blockchain.validator_registry.validators.get(m3_hash, {})
            if current.get('endpoint') == new_endpoint:
                print(f"[FVR] Endpoint ya actualizado: {new_endpoint}")
                return

            if isinstance(params, dict):
                params = CriterionParams(**params)

            proof = ZKEngine.generate_proof(priv, m3, m3_hash[:16], params, att)
            tx = Transaction(
                sender_m3=m3,
                receiver_m3=m3,
                amount=0,
                signature_data=proof,
                payload={
                    "op": "VALIDATOR_UPDATE",
                    "endpoint": new_endpoint,
                    "public_m3": m3,
                    "contraction_matrices": [a.tolist() for a in priv],
                }
            )
            if mempool.add_transaction(tx):
                print(f"[FVR] ✅ Endpoint auto-actualizado: {new_endpoint}")
            else:
                print(f"[FVR] ⚠️  No se pudo publicar endpoint: {new_endpoint}")
        except Exception as e:
            print(f"[FVR] Error en auto_update_endpoint: {e}")

    if args.miner_wallet:
        tasks.append(auto_update_endpoint())

    loop = asyncio.get_event_loop()
    shutdown_event = asyncio.Event()
    loop.add_signal_handler(signal.SIGTERM, shutdown_event.set)
    loop.add_signal_handler(signal.SIGINT,  shutdown_event.set)
    gather_task = asyncio.ensure_future(asyncio.gather(*tasks))
    try:
        await asyncio.wait([asyncio.ensure_future(shutdown_event.wait()), gather_task], return_when=asyncio.FIRST_COMPLETED)
        gather_task.cancel()
        try:
            await gather_task
        except asyncio.CancelledError:
            pass
    finally:
        print("[!] Flushing base de datos...")
        try:
            conn = storage._conn()
            conn.execute("PRAGMA wal_checkpoint(FULL)")
            conn.close()
            print("[✓] Base de datos cerrada limpiamente.")
        except Exception as e:
            print(f"[!] Error cerrando DB: {e}")







if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(main())
