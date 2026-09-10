"""Deterministic leader election and authenticated block commitments."""

import hashlib
import json

from blockchain.validator_registry import LAMBDA_MIN, LAMBDA_MAX

BLOCK_TIME_SECONDS = 60
EXCLUDED_VALIDATORS = {"ee481176"}


def election_context(chain, registry, current_slot):
    cutoff = max(0, current_slot // 100 - 1) * 100 * BLOCK_TIME_SECONDS
    anchor = chain[0]
    for block in reversed(chain):
        if block.timestamp < cutoff:
            anchor = block
            break
    validators = registry.get_validators_at(anchor.index)
    validators = [
        v for v in validators
        if not any(v["m3_hash"].startswith(prefix) for prefix in EXCLUDED_VALIDATORS)
    ]
    return anchor, validators


def expected_leader(chain, registry, timestamp):
    slot = int(timestamp // BLOCK_TIME_SECONDS)
    anchor, validators = election_context(chain, registry, slot)
    if not validators:
        return None
    scale = 10**12
    low = int(round(LAMBDA_MIN * scale))
    high = int(round(LAMBDA_MAX * scale))

    def lambda_fixed(validator):
        value = validator.get("lambda_value")
        if value is not None:
            return int(round(value * scale))
        value_hash = int(validator["m3_hash"], 16) % 2**32
        return low + ((high - low) * value_hash) // 2**32

    entropy = int(hashlib.sha256(f"{anchor.hash}{slot}".encode()).hexdigest(), 16)
    election_lambda = low + ((high - low) * entropy) // 2**256
    candidates = sorted(validators, key=lambda item: item["m3_hash"])
    return min(
        candidates,
        key=lambda item: (abs(lambda_fixed(item) - election_lambda), item["m3_hash"]),
    )["m3_hash"]


def producer_hash(block):
    transactions = []
    for tx in block.transactions:
        data = tx.to_dict()
        if not tx.sender_m3:
            data["signature_data"] = {"type": "COINBASE_V2"}
        transactions.append(data)
    content = {
        "chain_id": "metriplex-mainnet",
        "index": block.index,
        "timestamp": block.timestamp,
        "transactions": transactions,
        "previous_hash": block.previous_hash,
        "nonce": block.nonce,
    }
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
