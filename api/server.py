"""
Módulo API REST para el protocolo CAF.
Expone endpoints para interactuar con el nodo local, enviar transacciones
y consultar el estado del libro mayor.
"""

from typing import Optional  # NUEVO IMPORT

from blockchain.block import Transaction
from blockchain.chain import Blockchain
from fastapi import FastAPI, HTTPException
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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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

    @app.get("/balance/{tensor_hash}")
    def get_balance(tensor_hash: str):
        try:
            # OPTIMIZACIÓN: Consulta instantánea a la base de datos WAL
            # Evita el "State Replay" de recorrer toda la blockchain en memoria
            balance = blockchain.state_db.get_balance(tensor_hash)

            # Formateamos asumiendo que usas SCALE_FACTOR
            from core.arithmetic import SCALE_FACTOR

            return {
                "tensor_hash": tensor_hash,
                "balance_raw": balance,
                "balance_caf": balance / SCALE_FACTOR,
            }
        except Exception as e:
            return {"error": str(e)}

    @app.post("/transaction")
    async def submit_transaction(tx_req: TransactionRequest):
        try:
            # ACTUALIZADO: Ahora le pasamos el payload al motor interno
            tx = Transaction(
                sender_m3=tx_req.sender_m3,
                receiver_m3=tx_req.receiver_m3,
                amount=tx_req.amount,
                fee=tx_req.fee,  # <- ESTA LÍNEA FALTABA
                signature_data=tx_req.signature_data,
                payload=tx_req.payload,
            )

            success = mempool.add_transaction(tx)
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

    return app
