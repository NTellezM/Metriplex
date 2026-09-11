"""Consensus constants shared by nodes and transaction producers."""

CHAIN_ID = "metriplex-mainnet"

# Coordinated activation.  All validators and public clients must be upgraded
# before this height; older blocks keep their original validation rules.
TX_V2_ACTIVATION = 109_000

# Ata la prueba ZK a la clave del emisor. Antes de esta altura la tolerancia
# absoluta (2*SCALE_FACTOR) superaba en ~500x la magnitud de los tensores, de
# modo que el tensor empirico de CUALQUIER clave caia dentro del margen de
# CUALQUIER otra: la comprobacion no distinguia claves. Desde aqui el margen
# es relativo a la magnitud del tensor.
ZK_TOLERANCE_ACTIVATION = 111500  # despliegue coordinado 2026-09-11
# Margen permitido, en fraccion de max|public_m3|. Las pruebas legitimas
# observadas dan error 0; una falsificacion con otra clave ronda el 100%.
ZK_TOLERANCE_RATIO = 0.01

# Monetary values are stored as signed SQLite INTEGERs.
MAX_MONEY_RAW = 2**63 - 1

# Custody account used by validator stake and the native/EVM bridge.
STAKE_VAULT_M3_HASH = "f695d4a52988e1d55a0dc9650f5088bbe33b0c6934a88d96291ac865374ba0e0"
