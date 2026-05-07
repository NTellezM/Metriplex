import os
import time

import pytest
from blockchain.block import Block, Transaction
from blockchain.chain import Blockchain
from blockchain.storage import Storage
from core.arithmetic import SCALE_FACTOR
from core.verifier import calibrate
from crypto.keys import derive_public_key_with_attractor, generate_private_key
from crypto.signatures import sign_transaction
from network.mempool import Mempool

DB_TEST_PATH = "test_node.db"


@pytest.fixture
def setup_node():
    """Fixture que provee un entorno limpio (Storage, Chain, Mempool) para cada prueba."""
    if os.path.exists(DB_TEST_PATH):
        os.remove(DB_TEST_PATH)

    storage = Storage(DB_TEST_PATH)
    blockchain = Blockchain(storage)
    mempool = Mempool(blockchain)

    yield blockchain, mempool

    # Teardown
    if os.path.exists(DB_TEST_PATH):
        os.remove(DB_TEST_PATH)


@pytest.fixture
def test_identities():
    """Genera identidades garantizando que cumplan el criterio estricto."""
    from core.verifier import evaluate

    def generate_valid_identity():
        while True:
            priv = generate_private_key()
            pub, attr = derive_public_key_with_attractor(priv)
            params = calibrate(attr, priv["A"], priv["b"], len(priv["A"]))

            # Garantizar que la llave no es estocásticamente inestable (Evita fallos c8)
            res = evaluate(attr, priv["A"], priv["b"], params, len(attr))
            if res.pass_all:
                return {"priv": priv, "pub": pub, "attr": attr, "params": params}

    return {"A": generate_valid_identity(), "B": generate_valid_identity()}


def test_01_cryptography_and_zk_proof(test_identities):
    """Verifica que una firma compacta ZK-STARK es aceptada y detecta forgeability."""
    id_a = test_identities["A"]
    id_b = test_identities["B"]

    payload_dict = {
        "sender_m3": id_a["pub"],
        "receiver_m3": id_b["pub"],
        "amount": 50 * SCALE_FACTOR,
        "fee": 1 * SCALE_FACTOR,
        "payload": {},
    }

    # 1. Firma válida
    sig = sign_transaction(
        id_a["priv"],
        payload_dict,
        id_a["pub"],
        criterion_params=id_a["params"],
        attractor=id_a["attr"],
    )

    tx = Transaction(
        sender_m3=id_a["pub"],
        receiver_m3=id_b["pub"],
        amount=50 * SCALE_FACTOR,
        fee=1 * SCALE_FACTOR,
        signature_data=sig,
        payload={},
    )

    # Simular validación del nodo
    import hashlib
    import json

    tx_str = json.dumps(payload_dict, sort_keys=True).encode()
    tx_hash = hashlib.sha256(tx_str).hexdigest()

    from crypto.zkp import ZKEngine

    is_valid = ZKEngine.verify_proof(
        proof=sig,
        public_m3=id_a["pub"],
        tx_hash=tx_hash,
        criterion_params=id_a["params"],
        N_total=100,
    )
    assert is_valid is True, "La firma ZK legítima fue rechazada."

    # 2. Forgeability: Alterar el atractor (Ataque estructural)
    sig_forged = sig.copy()
    # Modificamos un punto del atractor
    sig_forged["x_final"] = [[0, 0, 0, 0] for _ in range(100)]

    is_valid_forged = ZKEngine.verify_proof(
        proof=sig_forged,
        public_m3=id_a["pub"],
        tx_hash=tx_hash,
        criterion_params=id_a["params"],
        N_total=100,
    )
    assert is_valid_forged is False, (
        "El sistema aceptó una prueba con atractor manipulado."
    )


def test_02_mempool_anti_spam(setup_node, test_identities):
    """Verifica que el mempool rechaza más de 5 transacciones pendientes por cuenta."""
    blockchain, mempool = setup_node
    id_a = test_identities["A"]
    id_b = test_identities["B"]

    # Faucet para A
    blockchain.state_db.mint(id_a["pub"], 1000 * SCALE_FACTOR)

    payload_dict = {
        "sender_m3": id_a["pub"],
        "receiver_m3": id_b["pub"],
        "amount": 1 * SCALE_FACTOR,
        "fee": 1 * SCALE_FACTOR,
        "payload": {},
    }

    # Insertar 5 transacciones (Deberían ser aceptadas)
    for i in range(5):
        # Alterar el payload para que el tx_hash sea único por iteración
        payload_dict["payload"] = {"nonce": i}
        sig = sign_transaction(
            id_a["priv"], payload_dict, id_a["pub"], id_a["params"], id_a["attr"]
        )
        tx = Transaction(
            id_a["pub"],
            id_b["pub"],
            1 * SCALE_FACTOR,
            sig,
            payload={"nonce": i},
            fee=1 * SCALE_FACTOR,
        )
        assert mempool.add_transaction(tx) is True

    # Insertar la 6ta transacción (Debería ser rechazada por anti-spam)
    payload_dict["payload"] = {"nonce": 5}
    sig = sign_transaction(
        id_a["priv"], payload_dict, id_a["pub"], id_a["params"], id_a["attr"]
    )
    tx6 = Transaction(
        id_a["pub"],
        id_b["pub"],
        1 * SCALE_FACTOR,
        sig,
        payload={"nonce": 5},
        fee=1 * SCALE_FACTOR,
    )
    assert mempool.add_transaction(tx6) is False, (
        "El filtro anti-spam falló al bloquear la 6ta TX."
    )


def test_03_mempool_fee_market(setup_node, test_identities):
    """Verifica que el mempool prioriza las transacciones con mayor fee."""
    blockchain, mempool = setup_node
    id_a = test_identities["A"]
    id_b = test_identities["B"]

    blockchain.state_db.mint(id_a["pub"], 1000 * SCALE_FACTOR)

    # TX 1 con fee de 1 CAF
    p1 = {
        "sender_m3": id_a["pub"],
        "receiver_m3": id_b["pub"],
        "amount": 10,
        "fee": 1 * SCALE_FACTOR,
        "payload": {"n": 1},
    }
    sig1 = sign_transaction(id_a["priv"], p1, id_a["pub"], id_a["params"], id_a["attr"])
    tx1 = Transaction(id_a["pub"], id_b["pub"], 10, sig1, {"n": 1}, 1 * SCALE_FACTOR)

    # TX 2 con fee de 5 CAF
    p2 = {
        "sender_m3": id_a["pub"],
        "receiver_m3": id_b["pub"],
        "amount": 10,
        "fee": 5 * SCALE_FACTOR,
        "payload": {"n": 2},
    }
    sig2 = sign_transaction(id_a["priv"], p2, id_a["pub"], id_a["params"], id_a["attr"])
    tx2 = Transaction(id_a["pub"], id_b["pub"], 10, sig2, {"n": 2}, 5 * SCALE_FACTOR)

    mempool.add_transaction(tx1)
    mempool.add_transaction(tx2)

    # Extraer lote
    batch = mempool.get_transactions_for_block(limit=10)
    assert len(batch) == 2
    assert batch[0].fee == 5 * SCALE_FACTOR, (
        "El ordenamiento por mercado de comisiones falló."
    )


def test_04_longest_chain_rule_and_balances(setup_node, test_identities):
    """Simula un fork y comprueba el State Replay y los saldos resultantes."""
    blockchain, mempool = setup_node
    id_a = test_identities["A"]
    id_b = test_identities["B"]

    # Asignar fondos iniciales
    tx_faucet = Transaction([], id_a["pub"], 1000 * SCALE_FACTOR, {"type": "COINBASE"})
    b1 = Block(1, [tx_faucet], blockchain.chain[-1].hash)
    blockchain.add_block(b1)

    # Crear una cadena paralela (competitiva) más larga
    new_chain = [blockchain.chain[0]]  # Empezar desde Génesis

    # B1 paralelo
    tx_faucet_alt = Transaction(
        [], id_a["pub"], 2000 * SCALE_FACTOR, {"type": "COINBASE"}
    )
    b1_alt = Block(1, [tx_faucet_alt], new_chain[-1].hash)
    new_chain.append(b1_alt)

    # B2 paralelo
    p_tx = {
        "sender_m3": id_a["pub"],
        "receiver_m3": id_b["pub"],
        "amount": 500 * SCALE_FACTOR,
        "fee": 10 * SCALE_FACTOR,
        "payload": {},
    }
    sig = sign_transaction(
        id_a["priv"], p_tx, id_a["pub"], id_a["params"], id_a["attr"]
    )
    tx_transfer = Transaction(
        id_a["pub"], id_b["pub"], 500 * SCALE_FACTOR, sig, {}, 10 * SCALE_FACTOR
    )

    b2_alt = Block(2, [tx_transfer], new_chain[-1].hash)
    new_chain.append(b2_alt)

    # Aplicar resolución de Fork
    success = blockchain.replace_chain(new_chain)

    assert success is True, "El protocolo rechazó una cadena de mayor peso."
    assert len(blockchain.chain) == 3, "La longitud de la cadena no se actualizó."

    # Comprobar State Replay (Saldos recalculados en base a la nueva cadena)
    bal_a = blockchain.state_db.get_balance(id_a["pub"])
    bal_b = blockchain.state_db.get_balance(id_b["pub"])

    assert bal_a == (2000 * SCALE_FACTOR) - (500 * SCALE_FACTOR) - (10 * SCALE_FACTOR)
    assert bal_b == 500 * SCALE_FACTOR
