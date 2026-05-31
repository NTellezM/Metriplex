# Convergent Emission Model — Metriplex Protocol
## Formal Definition

### Core equation
emission(n) = R₀(λ_mean) × e^(λ_mean × n / T_scale)

### Parameters
T_scale  = 7,059,101 blocks (13.4 years) — fixed calibration constant
λ_mean   = (1/|V|) × Σ λ(Wᵥ)           — dynamic, recalculated each epoch
R₀       = |λ_mean| / T_scale            — initial reward per block

### Supply convergence
Supply(∞) = ∫₀^∞ R₀ × e^(λ_mean × n / T_scale) dn
= R₀ × T_scale / |λ_mean|
= 1.0  × 21,000,000 MPX  (at current λ_mean = -0.6185)

### Supply as function of network geometry
λ_mean = -0.357  →  Supply ≈ 12.1M MPX  (1 validator, minimal diversity)
λ_mean = -0.619  →  Supply ≈ 21.0M MPX  (current state, 3 validators)
λ_mean = -0.700  →  Supply ≈ 23.8M MPX  (4-5 validators, good diversity)
λ_mean = -0.850  →  Supply ≈ 28.9M MPX  (6-8 validators, high diversity)
λ_mean = -1.000  →  Supply ≈ 34.0M MPX  (maximum practical diversity)
λ_mean = -1.204  →  Supply ≈ 40.9M MPX  (all validators at λ_min)

### Proof of convergence
Since all valid IFS satisfy ρ(Aᵢ) ∈ [0.30, 0.70]:
λ_mean ∈ [log(0.30), log(0.70)] ⊂ ℝ⁻   always
→ emission(n) → 0  as n → ∞
→ Supply(∞) < ∞    always
Convergence is guaranteed by IFS stability — not by an arbitrary cap.

### Voronoi reward distribution
reward_v(n) = emission(n) × |R_v| / Λ_range
|R_v|    = Voronoi cell size of validator v in λ-space
Λ_range  = log(0.70) - log(0.30) = 0.8473

### Key properties
1. No arbitrary cap — supply limit emerges from IFS geometry
2. More geometric diversity → larger monetary capacity
3. Validator incentive: maximize Voronoi territory → maximize reward
4. Network incentive: attract diverse validators → expand supply capacity
5. ERC-20 relationship: 1:1 today, evolves naturally as L1 adoption grows
6. Post-emission: validators earn exclusively from TX fees
7. Mathematical coherence: consensus geometry = monetary geometry = identity geometry

### Implementation phases
- Phase 2 (current): T_scale fixed, λ_mean fixed at current value → supply ≈ 21M
- Phase 3 (Fractal BFT): λ_mean dynamic from on-chain epoch registry
- Phase 4: ERC-20 contract redeployed to reflect convergent supply

### Relation to ERC-20
Current ERC-20 cap of 21M reflects Phase 2 supply at current validator geometry.
As validator set grows and diversifies, L1 supply ceiling naturally exceeds 21M.
The bridge relationship (1:1) will evolve to reflect the L1/ERC-20 supply ratio.
The ERC-20 is a liquidity access layer — the L1 is the canonical asset.

## Date: May 31, 2026
## Author: NTellezM (Nelson Tellez)
## Status: Formalized — partial implementation in miner.py (Phase 2)
## Full implementation: Phase 3 (Q3 2026) with Fractal BFT epoch registry
