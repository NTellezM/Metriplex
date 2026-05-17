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
    db_filename = f"node_data_{args.api_port}.db"

    rol_nodo = "OBSERVADOR (Full Node)" if args.no_miner else "VALIDADOR (Minero)"

    # --- Auto-detección de IP pública ---
    BOOTSTRAP_PEERS = [
        "157.180.113.24:65432",  # node-0 genesis
        "157.180.113.24:65433",  # NT-vps
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

    # --- Bootstrap peers ---
    if not args.peer:
        # Filtrar self — no conectar al propio puerto
        for bp in BOOTSTRAP_PEERS:
            bp_port = bp.split(":")[1]
            if str(args.p2p_port) != bp_port:
                args.peer = bp
                break

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

    p2p_node = CAFNode(
        host=P2P_HOST, port=args.p2p_port, blockchain=blockchain, mempool=mempool,
        host_public=public_ip
    )

    if args.peer:
        p2p_node.peers.add(args.peer)
        print(f"[Red] Configurado para conectar al peer: {args.peer}")

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
            block_time_seconds=10,
            miner_m3=miner_m3,
        )
        tasks.append(miner.start())

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[!] Apagado seguro iniciado.")
        sys.exit(0)
