"""Consensus constants shared by nodes and transaction producers."""

CHAIN_ID = "metriplex-mainnet"

# Coordinated activation.  All validators and public clients must be upgraded
# before this height; older blocks keep their original validation rules.
TX_V2_ACTIVATION = 109_000

# Monetary values are stored as signed SQLite INTEGERs.
MAX_MONEY_RAW = 2**63 - 1

# Custody account used by validator stake and the native/EVM bridge.
STAKE_VAULT_M3_HASH = "f695d4a52988e1d55a0dc9650f5088bbe33b0c6934a88d96291ac865374ba0e0"
