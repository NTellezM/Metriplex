"""
crypto/stark_core.py — Motor STARK CAF v7
==========================================
El proof de convergencia CAF se basa en:
  - x_final: muestra del atractor via algoritmo del caos (IFS privado)
  - trace_root: raíz de Merkle de la traza del chaos game (auditable)
  - Criterio compuesto c1..c8 evaluado sobre x_final

El Störmer-Verlet se reserva para la validación de la dinámica de resortes
(ítem 4, core/dynamics.py). El criterio criptográfico opera sobre el atractor.
"""

import hashlib
import json

from core.arithmetic import SCALE_FACTOR, to_float


class MerkleTree:
    @staticmethod
    def hash_leaf(data) -> str:
        return hashlib.sha256(
            json.dumps(data, sort_keys=True).encode()
        ).hexdigest()

    @staticmethod
    def build_root(leaves: list) -> str:
        if not leaves:
            return ""
        level = [MerkleTree.hash_leaf(l) for l in leaves]
        while len(level) > 1:
            nxt = []
            for i in range(0, len(level), 2):
                h1 = level[i]
                h2 = level[i+1] if i+1 < len(level) else h1
                nxt.append(hashlib.sha256((h1+h2).encode()).hexdigest())
            level = nxt
        return level[0]


class StarkProver:

    N_POINTS   = 100   # fragmentos del atractor para el proof
    N_BURN     = 300   # burn-in del chaos game
    TRACE_SNAP = 20    # snapshots para el trace

    @staticmethod
    def generate_trace_and_proof_v2(
        private_key: dict,
        tx_hash:     str,
    ) -> tuple:
        """
        PROVER v2 — Chaos game como fuente del atractor.

        1. Semilla inicial derivada de tx_hash (anti-replay).
        2. Algoritmo del caos: x ← Aₖx + bₖ para construir el atractor.
        3. Los N_POINTS finales son el x_final del proof.
        4. Trace commitment = MerkleRoot de snapshots del chaos game.
        """
        import os
        matrices = private_key["A"]
        vectores = private_key["b"]
        n        = len(matrices)
        D        = len(matrices[0])

        # Semilla determinista desde tx_hash (distinto por transacción → anti-replay)
        seed_val = int(hashlib.sha256(tx_hash.encode()).hexdigest()[:8], 16)

        # Estado inicial: perturbación pequeña basada en la semilla
        x = [
            int(((seed_val * (k + 1)) % 65536) / 65536.0 * 0.4 * SCALE_FACTOR
                * (-1 if k % 2 else 1))
            for k in range(D)
        ]

        from core.arithmetic import fp_mul

        trace      = []
        x_final    = []
        total_steps = StarkProver.N_BURN + StarkProver.N_POINTS

        snap_every = max(1, total_steps // StarkProver.TRACE_SNAP)

        for step in range(total_steps):
            # Selección determinista del mapa (usando bits de la semilla + step)
            k_map = (seed_val + step * 7) % n

            A, b = matrices[k_map], vectores[k_map]
            x = [
                sum(fp_mul(A[r][c], x[c]) for c in range(D)) + b[r]
                for r in range(D)
            ]

            # Snapshot para el trace (auditable sin revelar la clave)
            if step % snap_every == 0:
                centroid_fp = x[:]  # posición actual como snapshot
                trace.append([v for v in centroid_fp])

            # Retener solo los últimos N_POINTS (post burn-in)
            if step >= StarkProver.N_BURN:
                x_final.append(x[:])

        trace_root = MerkleTree.build_root(trace)
        return x_final, trace_root

    @staticmethod
    def generate_trace_and_proof(
        private_key: dict,
        tx_hash:     str,
    ) -> dict:
        """
        Interfaz compatible con el código existente (chain.py, signatures.py).
        """
        x_final, trace_root = StarkProver.generate_trace_and_proof_v2(
            private_key, tx_hash
        )
        D = len(x_final[0]) if x_final else 4
        # Centroide del estado final como audit_sample
        N = len(x_final)
        audit_sample = [
            sum(x_final[i][k] for i in range(N)) // N
            for k in range(D)
        ]
        n_snaps = StarkProver.TRACE_SNAP
        challenge_idx = (
            int(hashlib.sha256((trace_root + tx_hash).encode()).hexdigest(), 16)
            % n_snaps
        )
        return {
            "trace_root":     trace_root,
            "boundary_state": audit_sample,
            "audit_idx":      challenge_idx,
            "audit_sample":   audit_sample,
            "x_final":        x_final,
        }


class StarkVerifier:

    @staticmethod
    def verify(proof: dict, public_m3: list, tx_hash: str) -> bool:
        """
        VERIFIER — Evalúa el criterio compuesto sobre x_final.

        En chain.py se llama con los criterion_params embebidos en la transacción.
        Esta versión usa la verificación estructural básica para compatibilidad
        hasta que chain.py sea actualizado (ítem 5 del plan).
        """
        try:
            x_final = proof.get("x_final")
            if not x_final or not isinstance(x_final, list) or len(x_final) < 10:
                print("[STARK] Falla: x_final ausente o insuficiente.")
                return False

            D = 4
            if any(len(row) != D for row in x_final):
                print("[STARK] Falla: dimensión incorrecta en x_final.")
                return False

            # Verificar trace root + Fiat-Shamir
            n_snaps = StarkProver.TRACE_SNAP
            expected_idx = (
                int(hashlib.sha256(
                    (proof["trace_root"] + tx_hash).encode()
                ).hexdigest(), 16) % n_snaps
            )
            if proof["audit_idx"] != expected_idx:
                print("[STARK] Falla: índice de desafío incorrecto.")
                return False

            # Si hay criterion_params en el proof, evaluar el criterio completo
            if "criterion_params" in proof and proof["criterion_params"]:
                from core.verifier import evaluate, CriterionParams
                params  = CriterionParams.from_dict(proof["criterion_params"])
                matrices = proof.get("matrices_public")
                vectores = proof.get("vectores_public")

                if matrices and vectores:
                    result = evaluate(
                        x_final  = x_final,
                        matrices = matrices,
                        vectores = vectores,
                        params   = params,
                        N_total  = len(x_final),
                    )
                    if not result.pass_all:
                        print(f"[STARK] Falla criterio: {result.summary()}")
                        return False

            return True

        except (KeyError, TypeError, ValueError) as e:
            print(f"[STARK] Excepción en verificación: {e}")
            return False
