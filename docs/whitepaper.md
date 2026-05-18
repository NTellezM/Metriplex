<!--
  Metriplex Protocol — Technical Whitepaper
  Copyright (c) 2025-2026 NTellezM (Nelson Tellez)
  Licensed under Creative Commons Attribution 4.0 International (CC BY 4.0)
  https://creativecommons.org/licenses/by/4.0/
  
  Attribution required: cite as NTellezM, Metriplex Protocol (2025),
  https://github.com/NTellezM/Metriplex
-->

# Metriplex Protocol — Technical Whitepaper

**Version 2.0 · May 2026**  
*Order from chaos*

---

## Abstract

Metriplex is a Layer 1 blockchain that replaces elliptic curve cryptography with fractal geometry as the foundation for identity. Each account is represented by a unique strange attractor derived from a private Iterated Function System (IFS) in ℝ⁴. Transaction validity is proven through a composite geometric criterion (c1–c8) evaluated against this attractor, making forgery equivalent to solving the Inverse IFS Problem (IIFSP) — a problem conjectured to be computationally hard in the average case.

---

## 1. The Identity Problem in Traditional Blockchains

In Bitcoin, Ethereum, and most existing blockchains, account identity is derived from elliptic curve cryptography (ECDSA or EdDSA). A private key is a 256-bit random integer; the public key is a point on an elliptic curve; the address is a hash of that point.

This system has three fundamental limitations:

1. **Dimensional poverty**: identity is a 1-dimensional object (a number). Two accounts cannot be distinguished geometrically — only numerically.
2. **Quantum vulnerability**: Shor's algorithm breaks ECDSA in polynomial time on a quantum computer.
3. **No structural binding**: the private key has no mathematical relationship to the space in which transactions operate.

Metriplex addresses all three.

---

## 2. Fractal Identity

### 2.1 The IFS Private Key

A Metriplex private key is a set of n affine contractions in ℝᵈ:

```
K_priv = { (Aᵢ, bᵢ) }  for i = 1..n
where:
  Aᵢ ∈ ℝᵈˣᵈ  with ρ(Aᵢ) ∈ [0.30, 0.70]   (spectral radius)
  bᵢ ∈ ℝᵈ
  det(Aᵢ) > 0                                 (orientation-preserving, R1)
  ‖φ₃_ref‖ > ε_sym                             (minimum asymmetry, R2)
  n ≤ ⌊C(d+2,3)/3⌋                            (Kruskal uniqueness bound)
```

For the production parameters (n=4, d=4), these conditions guarantee that the IFS has a unique strange attractor μ_Q — the invariant measure of the system.

### 2.2 The M₃ Public Key

The public key is the third-order moment tensor of the attractor:

```
M₃ = E_μ[(x − μ̂) ⊗ (x − μ̂) ⊗ (x − μ̂)]
```

computed via the chaos game algorithm (2,000 iterations, 300 burn-in). The Kruskal rank condition guarantees that M₃ uniquely identifies the IFS — no two distinct systems can produce the same tensor.

### 2.3 Security Reduction

The security of the signature scheme reduces to the hardness of the Inverse IFS Problem (IIFSP): given M₃, find a set {(Aᵢ, bᵢ)} that produces it. By the Blum-Luby-Rubinfeld self-reduction theorem (BLR93), average-case hardness of IIFSP implies worst-case hardness, providing a formal security foundation.

### 2.4 Tensor Glyph — The Public Key Made Visible

The M₃ tensor is a 4×4×4 array of 64 float64 values encoding the third-order geometry of the attractor. Unlike a 256-bit integer, M₃ has intrinsic visual structure that can be rendered as a 2D identity image.

The **Tensor Glyph** is the canonical visual representation of a Metriplex identity:

```
For each pixel (px, py) in a canvas of size S:
  gx = (px / S) × 4,  gy = (py / S) × 4          # map to grid coords
  ix, iy = floor(gx), floor(gy)               # grid cell
  fx, fy = gx - ix, gy - iy                   # fractional offset

  # Bilinear interpolation of M₃ slices k=0,1,2
  r = bilinear(M₃[i][j][0], fx, fy)           # k=0 slice → R channel
  g = bilinear(M₃[i][j][1], fx, fy)           # k=1 slice → G channel
  b = bilinear(M₃[i][j][2], fx, fy)           # k=2 slice → B channel

  # Map to Metriplex color space (cyan ↔ purple ↔ teal)
  R = r×125 + b×42
  G = r×212 + g×174 + b×20
  B = r×248 + (1−r)×250×g
```

**Properties of the Tensor Glyph:**

- **Deterministic** — same M₃ always produces the same image
- **Unique** — by the Kruskal-Comon theorem, no two valid IFS produce the same M₃, therefore no two Tensor Glyphs are identical
- **Non-reversible** — the image cannot be used to reconstruct M₃ or the IFS
- **Public** — derived entirely from the public key; reveals no information about the private IFS
- **Continuous** — bilinear interpolation of the 4×4 tensor grid produces smooth gradients that reflect the geometric structure of the attractor

The Tensor Glyph replaces the conventional QR code in the Metriplex wallet. It is implemented in the browser wallet (`app.html`) and Chrome extension, and serves as the visual avatar of each fractal identity.

This is, to the authors' knowledge, the first instance of a cryptographic public key being rendered as a continuous color field derived directly from its mathematical structure — rather than as a hash-derived pattern or an arbitrary icon.


---

## 3. The Composite Criterion (ZK Proof)

Every transaction includes a zero-knowledge proof that the prover knows an IFS whose attractor satisfies 8 criteria simultaneously. The criteria are calibrated during key generation and published as public parameters.

| Criterion | Formula | Detects |
|-----------|---------|---------|
| c1 Δ_AS | ‖φ̂ − Σᵢ pᵢ φ̄(fᵢ(pos))‖² < θ_IFS | Non-self-similar distributions |
| c2 Var | Var(φ̂) > σ²_min | Concentrated / centroid attacks |
| c3 Frac | N_act/N > 0.50 | Fragment loss |
| c5 Skew | ‖φ₃(μ̂) − φ₃_ref‖ < τ | Reflection, rotation attacks |
| c6 Disp | μ₂(d_pairs) > d²_min | Discrete / cluster distributions |
| c7 Inv | ε_μ < θ_μ | Translation attacks |
| c8 Ratio | P₅/μ(d_pairs) > thresh | Fixed-point attacks |

The proof is generated by sampling 100 points from the attractor via a deterministic chaos game seeded from the transaction hash (anti-replay). The commitment is `MerkleRoot(x_final)` — revealing the geometric structure without revealing the IFS.

---

## 4. Consensus

Metriplex uses a slot-based Proof-of-Stake variant. Each slot selects a leader deterministically from the set of known validators using:

```
leader = validators[sha256(prev_hash + slot)  %  |validators|]
```

Block time: 10 seconds. Longest chain rule for fork resolution. Chain sync protocol for node synchronization.

---

## 5. Cross-Chain Bridge

The Ethereum bridge uses a lock-and-mint / burn-and-release architecture:

**Native → Ethereum:**
1. User sends MPX to the Vault address (a special IFS account)
2. User includes `target_eth_address` in the transaction payload
3. Relayer detects the TX and calls `mint(to, amount)` on the ERC-20 contract

**Ethereum → Native:**
1. User calls `burnForNative(amount, nativeRecipient)` on the contract
2. `nativeRecipient` is the JSON serialization of the user's M₃ tensor
3. Relayer detects the `BridgeBurn` event and submits a ZK-signed release TX from the Vault

---

## 6. Token Economics

| Parameter | Value |
|-----------|-------|
| Max supply | 21,000,000 MPX |
| Distribution | 40% liquidity / 30% vault / 20% team / 10% community |
| Block reward | 50 MPX per block |
| Bridge fee | 1 MPX per cross-chain transfer |

---

## 7. Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| Layer 1 core | ✅ Complete | IFS identity, ZK criterion, consensus, persistence |
| EVM bridge | ✅ Live (Base mainnet) | Relayer + ERC-20 contract, Uniswap V4 |
| Multi-node testnet | ✅ Live · May 2026 | 4 nodes across Chile and Germany, full mesh |
| Native browser TX | ✅ Live · May 16, 2026 | ZK proof generated in JS, verified on-chain |
| Tensor Glyph | ✅ Live · May 17, 2026 | M₃ public key rendered as continuous color field — visual fractal identity |
| Chrome Wallet Extension | ✅ Live · May 17, 2026 | Browser extension with ZK proof, Tensor Glyph, TX history |
| Rust rewrite | 🔜 Q3 2026 | 100x performance improvement |
| Security audit + arXiv | 🔜 Q1 2027 | ZK criterion formal verification + paper |

---

## 8. Fractal BFT

### 8.1 The Fork Problem

This is not a theoretical problem. It happened on May 18, 2026:
Slot 29651061:
node-0    sees peers: [node-0, NT-vps]         → leader = node-0    → mines block A
NT-laptop sees peers: [NT-laptop, node-0]       → leader = NT-laptop → mines block B
Both are correct according to their local view.
Result: two valid blocks in the same slot → FORK

The root cause is structural: the current leader election function
leader = validators[sha256(prev_hash + slot) % |validators|]

is deterministic given a fixed validator set — but each node computes it from its **local** peer list. If those lists diverge by even one entry, the modulo maps to a different index. With no communication before mining, there is no way to prevent it.

The longest-chain rule resolves forks eventually. But it cannot prevent them, and every fork wastes a block reward and temporarily splits the network state.

### 8.2 What BFT Solves

Byzantine Fault Tolerance protocols add a voting round before mining. The leader proposes; validators vote; the block is confirmed only when a supermajority agrees:
Slot N (without BFT):
Leader mines → broadcasts → some nodes accept, some don't → potential fork
Slot N (with BFT):

Leader proposes block
All validators receive proposal
Each votes: YES or NO
If >2/3 vote YES → block confirmed → everyone appends it
Fork is structurally impossible


The established protocols in this space:

| Protocol | Messages/block | Used by | Notes |
|----------|---------------|---------|-------|
| PBFT (1999) | O(n²) | Early systems | Works up to ~20 validators |
| Tendermint | O(n) | Cosmos | 3 phases: Propose → Prevote → Precommit |
| HotStuff | O(n) | Aptos | Linear BFT, most modern |

Metriplex Phase 2 targets a simplified Tendermint: three phases, no view-change complexity, tolerating 1 Byzantine node with 4 validators.

### 8.3 Fractal BFT Design

Fractal BFT extends slot-PoS with two structural additions:

**1. Global validator registry** — a deterministic on-chain list updated every epoch (1,000 blocks). All nodes compute leader election from the same committed set, eliminating split-brain.

**2. ZK identity proof per block** — the elected leader must embed a valid ZK criterion proof (c1–c8) evaluated against its own IFS attractor in the block header. Any node can verify authorship without trusting a PKI or coordinator.
block_header {
slot:          uint64
leader_m3:     tensor[4][4][4]   # leader public key
leader_proof:  ZKProof           # c1–c8 evaluated over leader_m3
prev_hash:     bytes32
attestations:  []Attestation     # 2f+1 ZK votes from validator set
}

### 8.4 Safety and Liveness

| Property | Mechanism |
|----------|-----------|
| Safety | ZK proof ties block authorship to IFS identity — unforgeable by IIFSP hardness |
| Liveness | If leader fails, next slot elects successor via same deterministic function |
| Fork prevention | Global registry + ZK identity eliminate divergent leader election |
| Finality | 2f+1 attestations from validator set (tolerates f Byzantine nodes) |
| Sybil resistance | Validator registration requires ZK identity proof — no anonymous validators |

### 8.5 ZK Voting: Identity-Bound Attestations

In Tendermint and HotStuff, a vote is an ECDSA signature. It proves *who* signed, but not that the signer has a cryptographic right to exist as a validator — that right is managed off-chain by a staking contract or a committee.

In Fractal BFT, each vote is a **mini ZK proof**:
Attestation {
validator_m3:  tensor[4][4][4]   # validator public key
slot:          uint64
block_hash:    bytes32
vote:          bool
zk_proof:      ZKProof           # c1–c8 over validator_m3
}

This is a structural difference. A single attestation simultaneously proves:
1. **Identity** — the signer possesses a valid IFS whose attractor matches M₃
2. **Authorship** — the proof was generated by the holder of the private IFS, not a copy
3. **Membership** — M₃ is registered in the on-chain validator set

An attacker cannot forge a vote by stealing a key. They would need to reconstruct the IFS from M₃ — equivalent to solving IIFSP, conjectured NP-hard in the average case. The cost of a Byzantine vote rises from *key theft* to *solving a hard geometric inverse problem*.

This also eliminates the need for a separate validator identity layer. The ZK criterion that authenticates transactions is the same mechanism that authenticates consensus votes. One primitive, two uses.

### 8.6 Implementation Plan (Phase 2 — Q3 2026)

| Step | Description | Target |
|------|-------------|--------|
| Epoch registry | On-chain validator list, committed every 1,000 blocks | Q3 2026 |
| Block header ZK | Leader proof required for block acceptance | Q3 2026 |
| Attestation protocol | ZK votes; 2f+1 threshold for finality | Q3 2026 |
| Slashing | Invalid ZK proof triggers validator ejection | Q3 2026 |
| Rust rewrite | BFT module implemented natively for 100x performance | Q3 2026 |

---

## 9. Network Milestones

### 9.3 First cross-country TX — May 14, 2026

| Event | Value |
|-------|-------|
| TX hash | 70757186c9a2a788f1dfdf2f388b3bb6... |
| ZK proof | ACCEPTED — c1–c8 verified |
| Propagation | Chile → Germany · ~10 seconds |
| Consensus | ✓ Identical — 4 nodes · 2 continents |

### 9.4 First native browser TX — May 16, 2026

| Event | Value |
|-------|-------|
| Proof generated | Browser (JavaScript) — metriplex-crypto.js |
| Proof verified | Python validator — ZK ACCEPTED |
| Bug fixed | `null` serialized as `{}` → tx_hash mismatch → resolved |
| Significance | Full ZK pipeline: JS → network → Python — no trusted intermediary |

---

### 9.5 Tensor Glyph — May 17, 2026

| Event | Value |
|-------|-------|
| Concept | M₃ tensor projected as 2D color field via bilinear interpolation |
| Properties | Deterministic, unique, non-reversible, continuous |
| Implementation | Browser wallet + Chrome extension (canvas API) |
| Significance | First public key rendered as continuous mathematical color field in blockchain |

### 9.6 Chrome Wallet Extension — May 17, 2026

| Event | Value |
|-------|-------|
| Features | Keystore unlock, ZK proof generation, send/receive, TX history, node selector |
| Identity | Tensor Glyph as visual avatar in wallet header and receive panel |
| API | Injects `window.metriplex` — dApp integration (MetaMask-style) |

---

*Metriplex Protocol — Order from chaos*
