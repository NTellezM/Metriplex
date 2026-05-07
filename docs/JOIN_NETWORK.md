# Join the Metriplex Network

Run your own node and participate in the first blockchain with fractal identity.

## Quick Install (Linux / macOS)

```bash
curl -sSL https://raw.githubusercontent.com/NTellezM/Metriplex/main/install.sh | bash
```

Or manually:

```bash
git clone https://github.com/NTellezM/Metriplex
cd Metriplex
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python main.py
```

---

## Node Types

### Validator Node (mines blocks + earns MPX rewards)

```bash
# 1. Create your wallet first
python wallet_cli.py
# → Option 1: Create wallet
# → Option 2: Export public key → pub_destino.json

# 2. Run the node with your wallet
python main.py --miner-wallet pub_destino.json
```

Every block you forge earns **50 MPX** in native rewards.

### Observer Node (full node, no mining)

```bash
python main.py --no-miner
```

### Connect to the Network

```bash
# Connect to an existing peer
python main.py --peer PEER_IP:65432

# Custom ports
python main.py --api-port 8001 --p2p-port 65433 --peer PEER_IP:65432
```

---

## What Your Node Does

When you run a Metriplex node:

1. **Downloads the chain** from connected peers
2. **Validates transactions** — verifies the ZK fractal criterion (c1–c8) for every TX
3. **Participates in consensus** — slot-based leader election
4. **Forges blocks** — if elected leader in a slot, mines the pending transactions
5. **Gossips** — propagates new blocks and transactions to peers

---

## System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| OS | Linux / macOS | Ubuntu 22.04+ |
| Python | 3.10+ | 3.12 |
| RAM | 512 MB | 2 GB |
| Storage | 1 GB | 10 GB |
| Network | 1 Mbps | 10 Mbps |

---

## API Endpoints

Once running, your node exposes a REST API at `http://localhost:8000`:

```bash
# Node status
curl http://localhost:8000/info

# Full chain
curl http://localhost:8000/blocks

# Account balance (replace HASH with tensor hash)
curl http://localhost:8000/balance/TENSOR_HASH

# Submit transaction
curl -X POST http://localhost:8000/transaction -d '{...}'

# Request testnet funds
curl -X POST http://localhost:8000/faucet -d '[[[...your M3 tensor...]]]'

# Force block production
curl -X POST http://localhost:8000/mine
```

---

## Running the Bridge Relayer

The relayer connects the native Metriplex chain to Ethereum (Base mainnet).

```bash
# Configure environment
cp .env.example .env
nano .env  # Add your EVM private key and vault password

# Run
VAULT_PASSWORD=your_password \
RELAYER_EVM_KEY=your_64_hex_key \
WEB3_RPC=https://mainnet.base.org \
python relayer.py
```

See [DEPLOY.md](DEPLOY.md) for full bridge configuration.

---

## Network Info

| Parameter | Value |
|-----------|-------|
| Token | MPX (Base Mainnet) |
| Contract | `0x22D3f414438556d1B071cCfE52513d4d829400fd` |
| Block time | 10 seconds |
| Block reward | 50 MPX |
| P2P port | 65432 (default) |
| API port | 8000 (default) |

---

## Troubleshooting

**Port already in use:**
```bash
python main.py --api-port 8001 --p2p-port 65433
```

**Node not syncing:**
```bash
# Delete local chain and resync
rm node_data_8000.db
python main.py --peer KNOWN_PEER_IP:65432
```

**Wallet not found:**
```bash
# Create wallet first
python wallet_cli.py
# Option 1 → Create wallet → Option 2 → Export to pub_destino.json
```

---

*Metriplex — Order from chaos*
