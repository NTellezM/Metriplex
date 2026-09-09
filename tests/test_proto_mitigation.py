"""Mitigación interina: bloquear ops de protocolo que llegan por el proxy público."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
import httpx
from api.server import create_api_app


def make_app():
    chain = SimpleNamespace(chain=[SimpleNamespace(index=1, hash="a"*64)],
                            validator_registry=SimpleNamespace(validators={}))
    # mempool que acepta todo, para aislar la mitigación de la API
    pool = SimpleNamespace(pending_transactions={}, add_transaction=Mock(return_value=True))
    node = SimpleNamespace(host_public="127.0.0.1", port=65432, peers=set(),
                           permanent_peers=set(), authenticated_peers={},
                           broadcast_transaction=None)
    async def bcast(tx): return None
    node.broadcast_transaction = bcast
    return create_api_app(chain, pool, node), pool


def tx_body(op=None):
    b = {"sender_m3": [[[1]]], "receiver_m3": [[[1]]], "amount": 0,
         "fee": 0, "signature_data": {"type": "X"}}
    if op:
        b["payload"] = {"op": op}
    return b


class MitigationTests(unittest.IsolatedAsyncioTestCase):
    async def test_protocol_op_via_proxy_is_blocked(self):
        app, pool = make_app()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            for op in ("VALIDATOR_REGISTER", "VALIDATOR_EXIT", "VALIDATOR_UPDATE", "VALIDATOR_GOVERNANCE_EXIT"):
                r = await c.post("/transaction", json=tx_body(op), headers={"X-Real-IP": "1.2.3.4"})
                self.assertEqual(r.status_code, 403, f"{op} debería bloquearse vía proxy")
        pool.add_transaction.assert_not_called()

    async def test_protocol_op_local_is_allowed(self):
        app, pool = make_app()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post("/transaction", json=tx_body("VALIDATOR_REGISTER"))  # sin X-Real-IP
            self.assertEqual(r.status_code, 200)
        pool.add_transaction.assert_called()

    async def test_normal_tx_via_proxy_is_allowed(self):
        app, pool = make_app()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post("/transaction", json=tx_body(), headers={"X-Real-IP": "1.2.3.4"})
            self.assertEqual(r.status_code, 200)  # TX normal no se ve afectada
        pool.add_transaction.assert_called()


if __name__ == "__main__":
    unittest.main()
