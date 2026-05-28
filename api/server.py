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
Módulo API REST para el protocolo CAF.
Expone endpoints para interactuar con el nodo local, enviar transacciones
y consultar el estado del libro mayor.
"""

from typing import Optional  # NUEVO IMPORT

from blockchain.block import Transaction
from blockchain.chain import Blockchain
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from network.mempool import Mempool
from pydantic import BaseModel


# ACTUALIZADO: El portero de la API ahora acepta payloads de contratos
class TransactionRequest(BaseModel):
    sender_m3: list
    receiver_m3: list
    amount: int
    fee: int = 0  # NUEVO
    signature_data: dict
    payload: Optional[dict] = None  # Permitir que sea opcional


def create_api_app(blockchain: Blockchain, mempool: Mempool, p2p_node) -> FastAPI:
    app = FastAPI(title="CAF Protocol Node API")

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        print(f"[API] 422 ERROR: {exc.errors()}")
        return JSONResponse(status_code=422, content={"detail": exc.errors()})

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/peers")
    async def get_peers():
        return {"peers": list(p2p_node.peers)}

    @app.get("/info")
    async def get_node_info():
        return {
            "chain_length": len(blockchain.chain),
            "mempool_size": len(mempool.pending_transactions),
            "latest_block_hash": blockchain.chain[-1].hash,
        }

    @app.get("/blocks")
    async def get_blocks(skip: int = 0, limit: int = 10):
        chain_data = [
            block.to_dict() if hasattr(block, "to_dict") else vars(block)
            for block in blockchain.chain
        ]
        return chain_data[::-1][skip : skip + limit]

    @app.get("/identity/{address}")
    def get_identity(address: str):
        """Devuelve el tensor M3 completo dado un hash de address (64 o 40 chars)."""
        import hashlib, json
        address = address.lower().replace('0x','')
        for block in blockchain.chain:
            for tx in block.transactions:
                for m3 in [tx.sender_m3, tx.receiver_m3]:
                    if not m3:
                        continue
                    h = hashlib.sha256(json.dumps(m3, sort_keys=True, separators=(',',':')).encode()).hexdigest()
                    if h.startswith(address):
                        return {"address": "0x"+h, "public_m3": m3}
        # Buscar en keystores conocidos (vault, etc.)
        import os
        known_keystores = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'vault_keystore.json'),
        ]
        for ks_path in known_keystores:
            try:
                ks = json.load(open(ks_path))
                m3 = ks.get('public_m3')
                if not m3:
                    continue
                h = hashlib.sha256(json.dumps(m3, sort_keys=True, separators=(',',':')).encode()).hexdigest()
                if h.startswith(address):
                    return {"address": "0x"+h, "public_m3": m3}
            except Exception:
                continue
        return {"error": "Identidad no encontrada en la chain"}

    @app.get("/balance/{tensor_hash}")
    def get_balance(tensor_hash: str):
        try:
            # Buscar con hash completo (64 chars) o prefijo (40 chars)
            balance = blockchain.storage.get_balance(tensor_hash)
            if balance == 0 and len(tensor_hash) <= 40:
                # Buscar en DB por prefijo
                import sqlite3
                conn = sqlite3.connect(blockchain.storage.db_path)
                cur = conn.cursor()
                cur.execute("SELECT balance FROM balances WHERE tensor_hash LIKE ?", (tensor_hash + '%',))
                row = cur.fetchone()
                conn.close()
                if row:
                    balance = row[0]

            # Formateamos asumiendo que usas SCALE_FACTOR
            from core.arithmetic import SCALE_FACTOR

            return {
                "tensor_hash": tensor_hash,
                "balance_raw": balance,
                "balance_caf": balance / SCALE_FACTOR,
            }
        except Exception as e:
            return {"error": str(e)}


    @app.get("/validators")
    async def get_validators():
        registry = blockchain.validator_registry
        return {
            "count": registry.size(),
            "validators": [
                {
                    "m3_hash": v["m3_hash"],
                    "endpoint": v["endpoint"],
                    "stake_mpx": v["stake"] // 1073741824,
                    "registered_at": v["registered_at"],
                    "lambda_value": v.get("lambda_value"),
                    "slashed": v.get("slashed", False),
                }
                for v in registry.get_sorted_validators()
            ],
            "slashed": list(registry.slashed),
            "mode": "FVR" if registry.size() > 0 else "Phase1-fallback",
        }

    @app.post("/transaction")
    async def submit_transaction(tx_req: TransactionRequest):
        try:
            print(f"[API] TX recibida sender={str(tx_req.sender_m3)[:20]} sig_keys={list(tx_req.signature_data.keys())[:5]}")
            # ACTUALIZADO: Ahora le pasamos el payload al motor interno
            tx = Transaction(
                sender_m3=tx_req.sender_m3,
                receiver_m3=tx_req.receiver_m3,
                amount=tx_req.amount,
                fee=tx_req.fee,  # <- ESTA LÍNEA FALTABA
                signature_data=tx_req.signature_data,
                payload=tx_req.payload,
            )

            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(None, mempool.add_transaction, tx)
            if success:
                # Propagar la transacción (gossip) a los demás nodos
                await p2p_node.broadcast_transaction(tx)
                return {"status": "success", "tx_id": tx.tx_id}
            else:
                raise HTTPException(
                    status_code=400,
                    detail="Transacción inválida o rechazada por el modelo matemático.",
                )

        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/faucet")
    async def request_funds(m3_tensor: list[list[list[int]]]):
        """Genera una transacción Coinbase para asignar fondos en Testnet."""
        import time
        from blockchain.block import Transaction
        from core.arithmetic import SCALE_FACTOR

        amount_fp = 1000 * SCALE_FACTOR

        # Nonce temporal para que cada solicitud genere un tx_id único
        # (sin esto, dos solicitudes del mismo tensor producen el mismo tx_id
        # y la segunda es rechazada por el mempool como duplicado)
        nonce = int(time.time() * 1000)

        tx = Transaction(
            sender_m3=[],
            receiver_m3=m3_tensor,
            amount=amount_fp,
            signature_data={"type": "COINBASE", "nonce": nonce},
        )

        if mempool.add_transaction(tx):
            await p2p_node.broadcast_transaction(tx)
            return {
                "status": "success",
                "message": "Transacción Faucet enviada a la red",
                "tx_id": tx.tx_id,
            }
        # Reportar el motivo real del rechazo
        return {
            "status": "error",
            "message": "El Mempool rechazó la TX (saldo suficiente o anti-spam activo)"
        }

    @app.post("/mine")
    async def mine_block():
        """
        Empaqueta las transacciones validadas del mempool en un nuevo bloque.
        """
        import time

        from blockchain.block import Block

        txs = mempool.get_transactions_for_block(limit=10)
        if not txs:
            return {
                "status": "ignored",
                "message": "Mempool vacío. No hay transacciones.",
            }

        last_block = blockchain.chain[-1]

        # En un sistema con Proof-of-Work, aquí se calcularía el Nonce.
        # En este diseño, el consenso recae en las firmas IIFSP, por lo que el bloque se forja directamente.
        new_block = Block(
            index=last_block.index + 1,
            transactions=txs,
            previous_hash=last_block.hash,
            timestamp=time.time(),
        )

        success = blockchain.add_block(new_block)

        if success:
            mempool.remove_mined_transactions(txs)
            return {
                "status": "success",
                "message": f"Bloque {new_block.index} forjado.",
                "block_hash": new_block.hash,
                "transactions_included": len(txs),
            }
        else:
            raise HTTPException(
                status_code=500, detail="Fallo al integrar el bloque a la cadena."
            )

    @app.post("/keystore/generate")
    async def generate_keystore(req: dict):
        """
        Genera un keystore Metriplex determinístico desde una address ERC-20.
        seed = sha256(evm_address) — mismo address + password = mismo keystore.
        """
        import hashlib, json, os, base64
        from cryptography.fernet import Fernet
        from crypto.keys import generate_private_key
        from crypto.keystore import save_keystore
        from crypto.tensors import calculate_m3_tensor
        from crypto.keys import chaos_game

        evm_address = req.get("address", "").lower().strip()
        password = req.get("password", "")

        if not evm_address.startswith("0x") or len(evm_address) != 42:
            raise HTTPException(status_code=400, detail="Address EVM inválida")
        if len(password) < 4:
            raise HTTPException(status_code=400, detail="Password demasiado corta")

        # Seed determinístico desde address
        seed_bytes = hashlib.sha256(evm_address.encode()).digest()
        seed_int = int.from_bytes(seed_bytes[:4], "little")

        import numpy as np
        rng = np.random.RandomState(seed_int % (2**31))

        # Generar IFS con seed fijo — reintentar hasta pasar c1-c8
        from crypto.keys import (
            _make_contraction, validate_r1, validate_scale,
            validate_kruskal, N, D, RHO_MIN, RHO_MAX, MAX_KEYGEN_ATTEMPTS,
            KRUSKAL_BOUND, secure_float, secure_int_fp
        )
        from core.verifier import calibrate, evaluate

        private_key = None
        for attempt in range(MAX_KEYGEN_ATTEMPTS):
            matrices, vectores = [], []
            for _ in range(N):
                scale = float(rng.uniform(RHO_MIN, RHO_MAX))
                from crypto.keys import _make_contraction_seeded
                matrices.append(_make_contraction_seeded(scale, rng))
                vectores.append([int(rng.uniform(-2**30, 2**30)) for _ in range(D)])
            r1_ok, _ = validate_r1(matrices)
            if not r1_ok:
                continue
            sc_ok, rhos = validate_scale(matrices)
            if not sc_ok:
                continue
            kr_ok, rank, _ = validate_kruskal(vectores, N)
            if not kr_ok:
                continue
            try:
                att = chaos_game(matrices, vectores)
                params = calibrate(att, matrices, vectores, len(att))
                result = evaluate(att, matrices, vectores, params, len(att))
                if not result.pass_all:
                    continue
                private_key = {"A": matrices, "b": vectores}
                criterion_params = params
                attractor = att
                break
            except Exception:
                continue

        if private_key is None:
            raise HTTPException(status_code=500, detail="No se pudo generar keystore válido")

        public_m3 = calculate_m3_tensor(attractor)
        address = "0x" + hashlib.sha256(
            json.dumps(public_m3, sort_keys=True, separators=(",",":")).encode()
        ).hexdigest()

        # Encriptar keystore (mismo formato que keystore.py)
        import struct
        salt = os.urandom(16)
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        from cryptography.hazmat.primitives import hashes
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=200000)
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        f = Fernet(key)
        encrypted = f.encrypt(json.dumps(private_key, separators=(",",":")).encode()).decode()

        keystore = {
            "address": address,
            "evm_address": evm_address,
            "salt": base64.b64encode(salt).decode(),
            "encrypted_private_key": encrypted,
            "public_m3": public_m3,
            "criterion_params": criterion_params,
            "attractor": attractor,
        }

        return {
            "keystore": keystore,
            "address": address,
            "evm_address": evm_address,
        }

    @app.post("/keystore/generate")
    async def generate_keystore(req: dict):
        import hashlib, json, os, base64
        import numpy as np
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        from cryptography.hazmat.primitives import hashes
        from crypto.keys import (
            _make_contraction_seeded, validate_r1, validate_scale,
            validate_kruskal, N, D, RHO_MIN, RHO_MAX, MAX_KEYGEN_ATTEMPTS,
        )
        from crypto.tensors import calculate_m3_tensor
        from crypto.keys import chaos_game
        from core.verifier import calibrate, evaluate

        evm_address = req.get("address", "").lower().strip()
        password = req.get("password", "")
        if not evm_address.startswith("0x") or len(evm_address) != 42:
            raise HTTPException(status_code=400, detail="Address EVM invalida")
        if len(password) < 4:
            raise HTTPException(status_code=400, detail="Password muy corta (min 4)")

        seed_int = int.from_bytes(hashlib.sha256(evm_address.encode()).digest()[:4], "little")
        rng = np.random.RandomState(seed_int % (2**31))

        private_key = criterion_params = attractor = None
        for _ in range(MAX_KEYGEN_ATTEMPTS):
            matrices, vectores = [], []
            for _ in range(N):
                scale = float(rng.uniform(RHO_MIN, RHO_MAX))
                matrices.append(_make_contraction_seeded(scale, rng))
                vectores.append([int(rng.uniform(-2**30, 2**30)) for _ in range(D)])
            if not validate_r1(matrices)[0]: continue
            if not validate_scale(matrices)[0]: continue
            if not validate_kruskal(vectores, N)[0]: continue
            try:
                att = chaos_game(matrices, vectores)
                params = calibrate(att, matrices, vectores, len(att))
                result = evaluate(att, matrices, vectores, params, len(att))
                if not result.pass_all: continue
                private_key, criterion_params, attractor = {"A": matrices, "b": vectores}, params, att
                break
            except Exception:
                continue

        if private_key is None:
            raise HTTPException(status_code=500, detail="No se pudo generar keystore valido")

        public_m3 = calculate_m3_tensor(attractor)
        address = "0x" + hashlib.sha256(
            json.dumps(public_m3, sort_keys=True, separators=(",",":")).encode()
        ).hexdigest()

        salt = os.urandom(16)
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=200000)
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        encrypted = Fernet(key).encrypt(json.dumps(private_key, separators=(",",":")).encode()).decode()

        return {
            "address": address,
            "evm_address": evm_address,
            "keystore": {
                "address": address,
                "evm_address": evm_address,
                "salt": base64.b64encode(salt).decode(),
                "encrypted_private_key": encrypted,
                "public_m3": public_m3,
                "criterion_params": criterion_params,
                "attractor": attractor,
            }
        }


    # ── Facial Identity ──────────────────────────────────────────────────
    import sqlite3 as _sqlite3, math as _math

    def _face_db():
        db = _sqlite3.connect('/opt/Metriplex/face_identity.db')
        db.execute("""CREATE TABLE IF NOT EXISTS face_identity (
            wallet TEXT PRIMARY KEY,
            lam REAL, ipd REAL, face_h REAL,
            nose_w REAL, mouth_w REAL, asym REAL,
            registered_at INTEGER
        )""")
        db.commit()
        return db

    def _face_dist(v1, v2):
        weights = [2.0, 1.5, 1.5, 1.0, 1.0, 0.8]
        return _math.sqrt(sum(w*(a-b)**2 for w,(a,b) in zip(weights, zip(v1,v2))))

    class FaceVector(BaseModel):
        wallet: str
        vector: list  # [lam, ipd, face_h, nose_w, mouth_w, asym]

    class FaceVerify(BaseModel):
        wallet: str
        vector: list

    @app.post("/identity/face/register")
    def face_register(req: FaceVector):
        if len(req.vector) != 6:
            raise HTTPException(status_code=400, detail="Vector debe tener 6 componentes")
        import time
        db = _face_db()
        try:
            db.execute("""INSERT OR REPLACE INTO face_identity
                (wallet, lam, ipd, face_h, nose_w, mouth_w, asym, registered_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                [req.wallet.lower()] + req.vector + [int(time.time())])
            db.commit()
            return {"status": "registered", "wallet": req.wallet.lower()}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            db.close()

    @app.post("/identity/face/verify")
    def face_verify(req: FaceVerify):
        THRESHOLD = 0.12
        db = _face_db()
        try:
            row = db.execute(
                "SELECT lam,ipd,face_h,nose_w,mouth_w,asym FROM face_identity WHERE wallet=?",
                [req.wallet.lower()]
            ).fetchone()
            if not row:
                return {"match": False, "reason": "wallet no registrada"}
            if len(req.vector) != 6:
                raise HTTPException(status_code=400, detail="Vector debe tener 6 componentes")
            dist = _face_dist(list(row), req.vector)
            confidence = max(0, 1 - dist / THRESHOLD)
            return {
                "match": dist < THRESHOLD,
                "confidence": round(confidence, 4),
                "delta": round(dist, 6),
                "threshold": THRESHOLD
            }
        finally:
            db.close()

    @app.get("/identity/face/{wallet}")
    def face_status(wallet: str):
        db = _face_db()
        try:
            row = db.execute(
                "SELECT lam, registered_at FROM face_identity WHERE wallet=?",
                [wallet.lower()]
            ).fetchone()
            if not row:
                return {"registered": False}
            return {
                "registered": True,
                "lambda": round(row[0], 6),
                "registered_at": row[1]
            }
        finally:
            db.close()

    return app
