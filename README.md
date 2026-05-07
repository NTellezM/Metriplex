<div align="center">

# Metriplex (MPX)

### *Order from chaos*

**The first blockchain with fractal identity**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://python.org)
[![Solidity 0.8.20](https://img.shields.io/badge/Solidity-0.8.20-purple.svg)](contracts/Metriplex.sol)
[![Network: Base](https://img.shields.io/badge/Network-Base-blue.svg)](https://base.org)

</div>

---

## What is Metriplex?

In every other blockchain, your identity is **a number**.  
In Metriplex, your identity is **a geometric shape** — a fractal attractor derived from a private Iterated Function System (IFS).

Your public key is not a 256-bit integer. It is a 4×4×4 tensor (M₃) that encodes the statistical geometry of your unique attractor. Two keys cannot collide because two distinct IFS systems cannot produce the same fractal geometry.

```
Traditional crypto:  identity = hash(random_number)
Metriplex:           identity = M₃(attractor(IFS))
```

## Architecture

```
┌─────────────────────────────────────────────────┐
│             Metriplex Layer 1 (native)           │
│                                                  │
│  Fractal Identity  ←→  ZK Proof  ←→  Consensus  │
│  (IFS + M₃ tensor)     (c1–c8)       (slot PoS) │
└──────────────────────┬──────────────────────────┘
                       │ relayer.py
┌──────────────────────▼──────────────────────────┐
│             Ethereum / Base (EVM Layer 2)        │
│                                                  │
│      Metriplex.sol (ERC-20, MPX token)           │
│      Uniswap V3 pair: MPX/ETH                   │
└─────────────────────────────────────────────────┘
```

## How it works

### Fractal Identity
When you create a wallet, the system generates a private IFS — a set of 4 affine contractions {(Aᵢ, bᵢ)} in ℝ⁴. These contractions define a unique fractal attractor. The public key is the third-order moment tensor M₃ of that attractor, computed via the chaos game algorithm.

### ZK Proof (c1–c8 composite criterion)
Every transaction includes a zero-knowledge proof that the sender knows an IFS whose attractor satisfies 8 geometric criteria simultaneously:
- **c1** Auto-similarity (Δ_AS < θ_IFS)
- **c2** Minimum variance (Var(φ̂) > σ²_min)
- **c3** Fragment completeness (N_act/N > 0.50)
- **c5** Asymmetry fingerprint (‖φ₃ − φ₃_ref‖ < τ)
- **c6** Pair dispersion (μ₂(d_pairs) > d²_min)
- **c7** Mean invariance (ε_μ < θ_μ)
- **c8** Cluster ratio (P₅/μ > thresh)

### Cross-chain bridge
The `relayer.py` oracle monitors both chains:
- **Native → Ethereum**: User sends MPX to the Vault. Relayer detects the TX and calls `mint()` on the ERC-20 contract.
- **Ethereum → Native**: User calls `burnForNative(amount, nativeRecipient)`. Relayer detects `BridgeBurn` event and releases MPX from the Vault.

---

## Quick Start

### 1. Install dependencies
```bash
git clone https://github.com/NTellezM/metriplex
cd metriplex
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment
```bash
cp .env.example .env
# Edit .env with your values
```

### 3. Run a node
```bash
# Validator node (mines blocks)
python main.py --miner-wallet pub_destino.json

# Observer node (no mining)
python main.py --no-miner

# Custom ports
python main.py --api-port 8001 --p2p-port 65433
```

### 4. Create a wallet
```bash
python wallet_cli.py
# Option 1: Create new wallet
# Option 2: Export public key → pub_destino.json
# Option 3: Request faucet funds (testnet)
# Option 4: Send MPX
```

### 5. Run the bridge relayer
```bash
# Set environment variables first (see .env.example)
VAULT_PASSWORD=your_password \
RELAYER_EVM_KEY=your_evm_private_key \
WEB3_RPC=https://sepolia.drpc.org \
python relayer.py
```

---

## Token (MPX)

| Parameter | Value |
|-----------|-------|
| Name | Metriplex |
| Symbol | MPX |
| Max Supply | 21,000,000 |
| Decimals | 18 |
| Network | Base (mainnet) |
| Contract (Sepolia) | `0x22D3f414438556d1B071cCfE52513d4d829400fd` |
| Uniswap | `TBD` |

### Distribution
```
40% (8.4M)  ── Uniswap V3 liquidity (locked)
30% (6.3M)  ── Bridge Vault (backing)
20% (4.2M)  ── Team / Development
10% (2.1M)  ── Community / Airdrop
```

---

## Smart Contract (ERC-20)

**Sepolia testnet (live):**  
`0x22D3f414438556d1B071cCfE52513d4d829400fd`  
[View on Etherscan](https://sepolia.etherscan.io/address/0x22D3f414438556d1B071cCfE52513d4d829400fd) · [TX Hash: mint live](https://sepolia.etherscan.io/tx/0x3c160ae311aeb2b35a3af6536f692307fc5f753d8e28fedeb006841e54557f53)

**Mainnet:** Coming soon on Base.

### Deploy your own (Remix IDE)
1. Open [remix.ethereum.org](https://remix.ethereum.org)
2. Load `contracts/Metriplex.sol`
3. Compile with Solidity 0.8.20
4. Deploy with your relayer address as constructor argument
5. Call `initialize(liquidityWallet)` once after deploy

---

## Project Structure

```
metriplex/
├── core/
│   ├── arithmetic.py      # Fixed-point arithmetic (S = 2³⁰)
│   ├── dynamics.py        # Störmer-Verlet integrator + CAFSimulator
│   ├── verifier.py        # Composite criterion c1–c8
│   └── vm.py              # Smart contract VM (DEPLOY, INVOKE)
├── crypto/
│   ├── keys.py            # IFS key generation (R1, R2, Kruskal)
│   ├── zkp.py             # ZK proof engine
│   ├── stark_core.py      # STARK prover/verifier
│   ├── tensors.py         # M₃ tensor computation
│   ├── keystore.py        # Encrypted wallet storage (PBKDF2 + Fernet)
│   └── signatures.py      # Transaction signing
├── blockchain/
│   ├── block.py           # Block + Transaction structures
│   ├── chain.py           # Blockchain + consensus validation
│   ├── state.py           # Account state (balances, contracts)
│   └── storage.py         # SQLite persistence
├── network/
│   ├── p2p.py             # TCP gossip network + chain sync
│   ├── miner.py           # AutoMiner (slot-based leader election)
│   └── mempool.py         # Transaction pool (fee-ordered, anti-spam)
├── api/
│   └── server.py          # FastAPI REST node
├── contracts/
│   └── Metriplex.sol      # ERC-20 bridge contract
├── main.py                # Node entry point
├── wallet_cli.py          # Interactive wallet CLI
├── relayer.py             # Cross-chain bridge oracle
├── requirements.txt
├── .env.example
└── README.md
```

---

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/info` | GET | Chain height, mempool size, latest hash |
| `/blocks` | GET | Full chain (all blocks + transactions) |
| `/balance/{tensor_hash}` | GET | Account balance |
| `/transaction` | POST | Submit signed transaction |
| `/faucet` | POST | Request testnet funds (M3 tensor in body) |
| `/mine` | POST | Force block production |
| `/peers` | GET | Connected P2P peers |

---

## Security Notes

- **Never commit** `.env`, `*_keystore.json`, `*.db`, or any file containing private keys.
- The `RELAYER_EVM_KEY` in `.env.example` is a placeholder — generate your own wallet.
- The Vault keystore is generated automatically by `relayer.py` on first run.
- Before mainnet deployment, consider a professional security audit of the ZK criterion.

---

## License

MIT © 2026 Metriplex Protocol

---

<div align="center">

**Metriplex** · *Order from chaos*

[Twitter](https://twitter.com/MetriplexMPX) · [Telegram](https://t.me/MetriplexMPX) · [Whitepaper](docs/whitepaper.md)

</div>
