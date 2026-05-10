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
Módulo de almacenamiento seguro de claves para CAF.
Implementa cifrado simétrico para persistir la identidad y el atractor en disco.
"""

import os
import json
import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.fernet import Fernet

def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=200000,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode()))

def save_keystore(
    password: str, 
    private_key: dict, 
    public_m3: list, 
    criterion_params: dict, 
    attractor: list,
    filepath: str = "keystore.json"
):
    salt = os.urandom(16)
    key = _derive_key(password, salt)
    f = Fernet(key)
    
    priv_data = json.dumps(private_key).encode()
    encrypted_priv = f.encrypt(priv_data).decode()
    
    keystore_data = {
        "salt": base64.b64encode(salt).decode(),
        "encrypted_private_key": encrypted_priv,
        "public_m3": public_m3,
        "criterion_params": criterion_params,
        "attractor": attractor
    }
    
    with open(filepath, "w") as f_out:
        json.dump(keystore_data, f_out)

def load_keystore(password: str, filepath: str = "keystore.json") -> tuple:
    if not os.path.exists(filepath):
        raise FileNotFoundError("El archivo keystore no existe.")
        
    with open(filepath, "r") as f_in:
        keystore_data = json.load(f_in)
        
    salt = base64.b64decode(keystore_data["salt"])
    key = _derive_key(password, salt)
    f = Fernet(key)
    
    try:
        decrypted_priv = f.decrypt(keystore_data["encrypted_private_key"].encode())
        private_key = json.loads(decrypted_priv.decode())
    except Exception:
        raise ValueError("Contraseña incorrecta o archivo corrupto.")
        
    return (
        private_key, 
        keystore_data["public_m3"], 
        keystore_data["criterion_params"], 
        keystore_data["attractor"]
    )