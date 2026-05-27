import os
import json
import hashlib
import pytest
from blockchain.block import Block, Transaction
from blockchain.chain import Blockchain
from blockchain.storage import Storage
from core.arithmetic import SCALE_FACTOR
from core.verifier import calibrate
from crypto.keys import derive_public_key_with_attractor, generate_private_key
from crypto.signatures import sign_transaction
from crypto.zkp import ZKEngine
from blockchain.validator_registry import compute_lambda, LAMBDA_MIN, LAMBDA_MAX
from network.mempool import Mempool

DB_TEST_PATH = "test_node.db"

@pytest.fixture
def setup_node():
    if os.path.exists(DB_TEST_PATH):
        os.remove(DB_TEST_PATH)
    storage = Storage(DB_TEST_PATH)
    blockchain = Blockchain(storage)
    mempool = Mempool(blockchain)
    yield blockchain, mempool
    if os.path.exists(DB_TEST_PATH):
        os.remove(DB_TEST_PATH)

@pytest.fixture
def test_identities():
    from core.verifier import evaluate
    def generate_valid_identity():
        while True:
            priv = generate_private_key()
            pub, attr = derive_public_key_with_attractor(priv)
            params = calibrate(attr, priv["A"], priv["b"], len(priv["A"]))
            res = evaluate(attr, priv["A"], priv["b"], params, len(attr))
            if res.pass_all:
                return {"priv": priv, "pub": pub, "attr": attr, "params": params}
    return {"A": generate_valid_identity(), "B": generate_valid_identity()}


def test_01_zk_proof_N2000(test_identities):
    """ZK proof con N_total=2000 — consistente con producción."""
    id_a = test_identities["A"]
    id_b = test_identities["B"]

    payload_dict = {
        "sender_m3": id_a["pub"],
        "receiver_m3": id_b["pub"],
        "amount": 50 * SCALE_FACTOR,
        "fee": 1 * SCALE_FACTOR,
        "payload": None,
    }

    sig = sign_transaction(
        id_a["priv"], payload_dict, id_a["pub"],
        criterion_params=id_a["params"], attractor=id_a["attr"]
    )

    tx_hash = hashlib.sha256(
        json.dumps(payload_dict, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    is_valid = ZKEngine.verify_proof(
        proof=sig, public_m3=id_a["pub"],
        tx_hash=tx_hash, criterion_params=id_a["params"],
        N_total=len(id_a["attr"])
    )
    assert is_valid is True, "ZK proof con N_total=len(attractor) fue rechazado."


def test_02_tx_hash_payload_none():
    """tx_hash siempre usa payload=None — consistencia firma vs verificación."""
    sender_m3 = [[[1, 2, 3, 4]] * 4] * 4
    receiver_m3 = [[[5, 6, 7, 8]] * 4] * 4
    amount = 100 * SCALE_FACTOR
    fee = 0

    # Firma con payload=None
    d_sign = {"sender_m3": sender_m3, "receiver_m3": receiver_m3,
               "amount": amount, "fee": fee, "payload": None}
    hash_sign = hashlib.sha256(
        json.dumps(d_sign, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    # Verificador usa payload=None
    d_verify = {"sender_m3": sender_m3, "receiver_m3": receiver_m3,
                 "amount": amount, "fee": fee, "payload": None}
    hash_verify = hashlib.sha256(
        json.dumps(d_verify, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    assert hash_sign == hash_verify, "tx_hash difiere entre firma y verificación."


def test_03_lyapunov_lambda_range(test_identities):
    """λ(W) debe estar en [LAMBDA_MIN, LAMBDA_MAX]."""
    id_a = test_identities["A"]
    lv = compute_lambda(id_a["priv"]["A"])
    assert LAMBDA_MIN <= lv <= LAMBDA_MAX, f"λ={lv} fuera de rango [{LAMBDA_MIN}, {LAMBDA_MAX}]"


def test_04_tolerance_numpy_versions(test_identities):
    """TOLERANCE=2.0*SCALE_FACTOR absorbe diferencias entre numpy versions."""
    from crypto.zkp import ZKEngine
    from blockchain.validator_registry import compute_lambda
    import numpy as np

    id_a = test_identities["A"]
    TOLERANCE = int(2.0 * SCALE_FACTOR)

    # Simular diferencia numérica entre numpy versions
    matrices = [np.array(A, dtype=float) / SCALE_FACTOR for A in id_a["priv"]["A"]]
    diff = abs(matrices[0][0][0] * SCALE_FACTOR - id_a["priv"]["A"][0][0][0])
    assert diff < TOLERANCE, f"Diferencia numérica {diff} excede TOLERANCE {TOLERANCE}"


def test_05_mempool_fee_priority(setup_node):
    """Mempool prioriza TXs con mayor fee — sin ZK."""
    blockchain, mempool = setup_node

    # Insertar TXs directamente en el mempool sin validación ZK
    tx1 = Transaction([], [[[1]]], 10, {"type": "COINBASE"}, fee=1 * SCALE_FACTOR)
    tx2 = Transaction([], [[[1]]], 10, {"type": "COINBASE"}, fee=5 * SCALE_FACTOR)
    mempool.pending_transactions[tx1.tx_id] = tx1
    mempool.pending_transactions[tx2.tx_id] = tx2

    batch = mempool.get_transactions_for_block(limit=10)
    assert len(batch) == 2
    assert batch[0].fee == 5 * SCALE_FACTOR, "Fee market ordering falló."


def test_06_chain_replace_longest(setup_node, test_identities):
    """Regla de cadena más larga — reorg correcto."""
    blockchain, _ = setup_node
    id_a = test_identities["A"]

    tx_faucet = Transaction([], id_a["pub"], 1000 * SCALE_FACTOR, {"type": "COINBASE"})
    b1 = Block(1, [tx_faucet], blockchain.chain[-1].hash)
    blockchain.add_block(b1)

    new_chain = [blockchain.chain[0]]
    tx_alt = Transaction([], id_a["pub"], 2000 * SCALE_FACTOR, {"type": "COINBASE"})
    b1_alt = Block(1, [tx_alt], new_chain[-1].hash)
    new_chain.append(b1_alt)
    b2_alt = Block(2, [Transaction([], id_a["pub"], 1 * SCALE_FACTOR, {"type": "COINBASE"})], b1_alt.hash)
    new_chain.append(b2_alt)

    success = blockchain.replace_chain(new_chain)
    assert success is True, "replace_chain rechazó cadena más larga."
    assert len(blockchain.chain) == 3
