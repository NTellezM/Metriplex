# Metriplex (MPX)

<p align="center">
  <img src="assets/logo6.png" alt="Metriplex" width="200"/>
</p>

### *Order from chaos*

**The first blockchain with fractal identity**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![License: BUSL-1.1](https://img.shields.io/badge/License-BUSL--1.1-blue.svg)](LICENSE-CORE)
[![License: CC BY 4.0](https://img.shields.io/badge/License-CC%20BY%204.0-lightgrey.svg)](LICENSE-DOCS)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](https://python.org)
[![Solidity 0.8.20](https://img.shields.io/badge/Solidity-0.8.20-purple.svg)](contracts/Metriplex.sol)
[![Network: Base](https://img.shields.io/badge/Network-Base-blue.svg)](https://base.org)

---

## What is Metriplex?

In every other blockchain, your identity is **a number**.  
In Metriplex, your identity is **a geometric shape** — a fractal attractor derived from a private Iterated Function System (IFS).

Your public key is not a 256-bit integer. It is a 4×4×4 tensor (M₃) that encodes the statistical geometry of your unique attractor. Two keys cannot collide because two distinct IFS systems cannot produce the same fractal geometry.

```
Traditional crypto:  identity = hash(random_number)
Metriplex:           identity = M₃(attractor(IFS))
```

---

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
│      Uniswap V4 pair: MPX/ETH (1% fee)          │
└─────────────────────────────────────────────────┘
```

---

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

### 1. One-line install

```bash
curl -sSL https://metriplexmpx.xyz/install.sh | bash
```

### 2. Manual install

```bash
git clone https://github.com/NTellezM/Metriplex
cd Metriplex
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env with your values
```

### 4. Run a node

```bash
# Validator node (mines blocks)
python main.py --miner-wallet pub_destino.json

# Observer node (no mining)
python main.py --no-miner

# Custom ports
python main.py --api-port 8001 --p2p-port 65433
```

### 5. Create a wallet

```bash
python wallet_cli.py
# Option 1: Create new wallet
# Option 2: Export public key → pub_destino.json
# Option 3: Request faucet funds (testnet)
# Option 4: Send MPX
```

### 6. Run the bridge relayer

```bash
VAULT_PASSWORD=your_password \
RELAYER_EVM_KEY=your_evm_private_key \
WEB3_RPC=https://mainnet.base.org \
python relayer.py
```

---

## Token (MPX)

| Parameter | Value |
|-----------|-------|
| Name | Metriplex |
| Symbol | MPX |
| Max Supply | 21,000,000 (fixed forever) |
| Decimals | 18 |
| Network | Base (mainnet) |
| Contract | [`0x22D3f414438556d1B071cCfE52513d4d829400fd`](https://basescan.org/token/0x22D3f414438556d1B071cCfE52513d4d829400fd) |
| Uniswap V4 | [Trade MPX](https://app.uniswap.org/explore/tokens/base/0x22d3f414438556d1b071ccfe52513d4d829400fd) |
| GeckoTerminal | [View pool](https://www.geckoterminal.com/base/pools/0x42f8cd7f7e80e8e1fa7b0d41e3a83e5c5b73b0e) |

### Distribution

```
40% (8.4M)  ── Uniswap V4 liquidity
60% (12.6M) ── Founder / development / future listings
```

No investors. No private sale. No vesting.  
Block reward: 50 MPX per block (native mining).

---

## Smart Contract (ERC-20)

**Base mainnet (live):**  
`0x22D3f414438556d1B071cCfE52513d4d829400fd`  
[View on BaseScan](https://basescan.org/token/0x22D3f414438556d1B071cCfE52513d4d829400fd)

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

This repository uses a **dual license structure**:

| Component | License |
|-----------|---------|
| Node, API, Bridge, Contracts (`main.py`, `api/`, `network/`, `blockchain/`, `contracts/`) | [MIT](LICENSE) |
| Cryptographic Core (`core/`, `crypto/`) | [BUSL-1.1](LICENSE-CORE) → MIT on 2027-05-09 |
| Whitepaper & Docs (`docs/`) | [CC BY 4.0](LICENSE-DOCS) |

The cryptographic core (fractal identity, ZK criterion c1–c8, tensor operations) is available for non-production use (research, education, personal). Production use requires a commercial license until May 2027, when it automatically becomes MIT.

**Academic citation:**

```
NTellezM (Nelson Tellez). "Metriplex: Fractal Identity as a Cryptographic Primitive
on a Layer 1 Blockchain." 2026. https://github.com/NTellezM/Metriplex
```

---

## Contact

- Developer: ntellezm@gmail.com
- Project: metriplexmpx@gmail.com
- Website: [metriplexmpx.xyz](https://metriplexmpx.xyz)
- Twitter: [@MetriplexMPX](https://twitter.com/MetriplexMPX)
- Whitepaper: [docs/whitepaper.md](docs/whitepaper.md)

---

**Metriplex** · *Order from chaos*
