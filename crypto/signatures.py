# SPDX-License-Identifier: BUSL-1.1
#
# Metriplex Cryptographic Core
# Copyright (c) 2025-2026 NTellezM (Nelson Tellez)
#
# This file is part of the Metriplex Cryptographic Core, licensed under
# the Business Source License 1.1 (BUSL-1.1).
#
# Non-production use (research, education, personal projects) is permitted.
# Production use requires a commercial license until 2027-05-09, after which
# this file is available under the MIT License.
#
# Contact: metriplexmpx@gmail.com
# License: See LICENSE-CORE in the repository root
#
"""
Módulo de firmas criptográficas basadas en el IIFSP.
"""

import hashlib
import json

from crypto.zkp import ZKEngine
from core.verifier import calibrate
from crypto.keys import chaos_game

def sign_transaction(
    private_key: dict, 
    tx_payload_dict: dict, 
    sender_public_m3: list,
    criterion_params = None,
    attractor: list = None
) -> dict:
    tx_str = json.dumps(tx_payload_dict, sort_keys=True, separators=(",",":")).encode()
    tx_hash = hashlib.sha256(tx_str).hexdigest()

    matrices = private_key["A"]
    vectores = private_key["b"]
    
    # Uso de caché: Si no se proveen, se re-calculan en tiempo de ejecución (costoso)
    if attractor is None or criterion_params is None:
        attractor = chaos_game(matrices, vectores)
        n_maps = len(matrices)
        criterion_params = calibrate(attractor, matrices, vectores, n_maps)

    stark_proof = ZKEngine.generate_proof(
        private_key=private_key,
        public_m3=sender_public_m3,
        tx_hash=tx_hash,
        criterion_params=criterion_params,
        N_total=len(attractor) if attractor else 100,
        attractor=attractor
    )
    
    stark_proof["criterion_params"] = criterion_params.to_dict() if hasattr(criterion_params, "to_dict") else vars(criterion_params)
    
    return stark_proof