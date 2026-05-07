# Deployment Guide — Metriplex (MPX)

## Prerequisites

- Python 3.12+
- Node.js 18+ (for dashboard only)
- A wallet with ETH on Base or Sepolia
- Access to a Sepolia/Base RPC endpoint

---

## 1. Local Node (Development)

```bash
# Clone and install
git clone https://github.com/YOUR_USERNAME/metriplex
cd metriplex
python -m venv venv
source venv/bin/activate        # Linux/Mac
# venv\Scripts\activate         # Windows
pip install -r requirements.txt

# Configure
cp .env.example .env

# Run node (port 8000)
python main.py --miner-wallet pub_destino.json
```

The node exposes:
- REST API: `http://localhost:8000`
- P2P TCP:  `localhost:65432`

---

## 2. Multi-Node Setup

```bash
# Node 1 (primary, port 8000)
python main.py --api-port 8000 --p2p-port 65432

# Node 2 (connects to node 1)
python main.py --api-port 8001 --p2p-port 65433 --peer 127.0.0.1:65432

# Node 3 (observer only, no mining)
python main.py --api-port 8002 --p2p-port 65434 --peer 127.0.0.1:65432 --no-miner
```

---

## 3. Smart Contract Deployment (Remix)

### Testnet (Sepolia)
1. Open [remix.ethereum.org](https://remix.ethereum.org)
2. Create file `contracts/Metriplex.sol` — paste content from this repo
3. Install OpenZeppelin: use the GitHub import URL in Remix
4. Compile: Solidity 0.8.20, optimization enabled
5. Deploy:
   - Environment: **Injected Provider (MetaMask/Brave)**
   - Network: **Sepolia Testnet**
   - Constructor arg: your relayer wallet address (`0x...`)
6. After deploy, call `initialize(your_wallet_address)`
7. Verify on Etherscan (Sourcify option in Remix)

### Mainnet (Base)
Same steps, but select **Base Mainnet** in MetaMask.

Network config for Brave/MetaMask:
```
Name:     Base
RPC:      https://mainnet.base.org
Chain ID: 8453
Symbol:   ETH
Explorer: https://basescan.org
```

---

## 4. Bridge Relayer

```bash
# Set environment variables
export RELAYER_EVM_KEY="your_64_char_hex_private_key"
export VAULT_PASSWORD="your_vault_password"
export WEB3_RPC="https://mainnet.base.org"
export MXP_NODE_URL="http://localhost:8000"

# Run
python relayer.py
```

On first run, `relayer.py` generates `vault_keystore.json` and prints the Vault's M₃ tensor.
**Copy that tensor and update `VAULT_MPX_ADDRESS` in `relayer.py`** before restarting.

---

## 5. Uniswap V3 Liquidity (Base Mainnet)

After deploying and calling `initialize()`:

1. Go to [app.uniswap.org](https://app.uniswap.org)
2. Switch MetaMask to **Base Mainnet**
3. Pool → New Position → Select tokens: MPX + ETH
4. Fee tier: **1%** (recommended for new tokens)
5. Price range: **Full Range**
6. Add your liquidity amount (minimum ~$100 equivalent)
7. Confirm transaction

The pair will appear on [Dexscreener](https://dexscreener.com) automatically within minutes of first trade.

---

## 6. Environment Variables Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `RELAYER_EVM_KEY` | Yes | 64-char hex private key of the relayer wallet |
| `VAULT_PASSWORD` | Yes | Password for vault_keystore.json |
| `VAULT_KEYSTORE` | No | Path to vault keystore (default: `vault_keystore.json`) |
| `WEB3_RPC` | No | Ethereum RPC URL (default: `https://sepolia.drpc.org`) |
| `MXP_NODE_URL` | No | Native node URL (default: `http://localhost:8000`) |
