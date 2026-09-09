# Join the Metriplex Network

Run your own node and participate in the first blockchain with fractal cryptographic identity.

---

## Option 0 — One command (Recommended)

Installs dependencies, bootstraps from the latest snapshot (syncs in seconds),
sets up a `systemd` service, and starts the node. Run as root.

```bash
# Observer node (read-only)
curl -sSL https://metriplexmpx.xyz/join.sh | sudo bash

# Validator node (generates a fractal identity + keystore)
curl -sSL https://metriplexmpx.xyz/join.sh | sudo bash -s -- --validator --public-ip YOUR_IP
```

Flags: `--validator` / `--observer` (default), `--api-port N`, `--p2p-port N`,
`--peer IP:PORT`, `--public-ip IP`, `--dir PATH`. Multiple nodes on one machine
auto-pick free ports and get isolated `.env.<port>` files.

### Activating a validator

A validator node prints its fractal identity when it starts. To activate it:

1. Send **100 MPX** of stake to that identity.
2. Register and switch the node to mining:

```bash
bash /opt/Metriplex/scripts/register-validator.sh --api-port PORT --public-ip YOUR_IP
```

The script verifies the stake, computes your Lyapunov λ, checks geometric
diversity, signs and submits the `VALIDATOR_REGISTER`, and — once it appears in
the FVR — flips the systemd service from observer to miner.

Need stake? Contact the team.

---

## Option 1 — Docker (advanced)

The fastest way to run a node. No Python setup required.

```bash
git clone https://github.com/NTellezM/Metriplex
cd Metriplex

# Observer node (full node, no mining)
NO_MINER=1 docker-compose up -d

# Check status
curl http://localhost:8000/info
```

Your node will automatically sync with the network (~7,500+ blocks, takes a few minutes).

### Validator Node (Docker)

```bash
# 1. Generate your keystore
docker run --rm -v metriplex-data:/data ntellezm/metriplex:latest \
  python3 wallet_cli.py generate --output /data/keystore.json

# 2. Run validator
MINER_WALLET=keystore.json MINER_PASSWORD=your_password docker-compose up -d
```

---

## Option 2 — Manual (Linux / macOS)

```bash
git clone https://github.com/NTellezM/Metriplex
cd Metriplex
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### Observer Node

```bash
python3 main.py --no-miner --peer 157.180.113.24:65432
```

### Validator Node

```bash
# 1. Generate encrypted keystore
python3 wallet_cli.py

# 2. Run with keystore
export MINER_PASSWORD=your_password
python3 main.py --miner-wallet keystore.json --peer 157.180.113.24:65432
```

---

## Node Types

| Type | Description | Earns MPX |
|------|-------------|-----------|
| Validator | Mines blocks, participates in FVR | Voronoi-weighted (≈1–2 MPX/block) |
| Observer | Full node, verifies all ZK proofs | No |

---

## What Your Node Does

1. **Downloads the chain** from connected peers (skip_zk sync — fast)
2. **Validates transactions** — verifies ZK fractal criterion (c1–c8) for every TX
3. **GEO_HANDSHAKE** — authenticates peers via ZK proof of fractal identity
4. **Participates in consensus** — deterministic slot-based leader election
5. **Forges blocks** — if elected leader in a slot, mines pending transactions
6. **Gossips** — propagates blocks and transactions across the network

---

## System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| OS | Linux / macOS | Ubuntu 22.04+ |
| Python | 3.10+ | 3.12 |
| RAM | 512 MB | 2 GB |
| Storage | 2 GB | 20 GB |
| Network | 1 Mbps | 10 Mbps |
| Ports | 8000, 65432 | Open in firewall/router |

---

## API Endpoints

```bash
# Node status
curl http://localhost:8000/info

# Validators (FVR)
curl http://localhost:8000/validators

# Account balance
curl http://localhost:8000/balance/TENSOR_HASH_8CHARS

# Submit transaction
curl -X POST http://localhost:8000/transaction -H 'Content-Type: application/json' -d '{...}'
```

---

## Network Parameters

| Parameter | Value |
|-----------|-------|
| Token | MPX (Base Mainnet) |
| Contract | `0x22D3f414438556d1B071cCfE52513d4d829400fd` |
| Block time | 60 seconds |
| Block reward | Convergent fractal emission (Voronoi-weighted) |
| P2P port | 65432 (default) |
| API port | 8000 (default) |
| Genesis peer | `157.180.113.24:65432` |

---

## Troubleshooting

**Port already in use:**
```bash
python3 main.py --api-port 8001 --p2p-port 65433 --peer 157.180.113.24:65432
```

**Node not syncing:**
```bash
rm node_data_8000.db
python3 main.py --no-miner --peer 157.180.113.24:65432
```

**Fork on startup:**
The node automatically detects chain divergence and resyncs before mining.
If stuck, delete the DB and restart — sync takes ~2 minutes.

---

*Metriplex — Order from chaos · [metriplexmpx.xyz](https://metriplexmpx.xyz)*
