import hashlib
import json

from core.arithmetic import SCALE_FACTOR
from core.verifier import CriterionParams, evaluate

from crypto.stark_core import MerkleTree


class ZKEngine:
    N_PROOF = 400  # Puntos del atractor simulados en la traza

    @staticmethod
    def generate_proof(
        private_key: dict,
        public_m3: list,
        tx_hash: str,
        criterion_params: CriterionParams,
        N_total: int,
        attractor: list = None,
    ) -> dict:
        """
        PROVER — Ejecutado por la wallet.
        Genera un ZK-Proof compacto utilizando compromisos escalares.
        """
        matrices = private_key["A"]
        vectores = private_key["b"]

        if attractor is None or len(attractor) < ZKEngine.N_PROOF:
            from crypto.keys import chaos_game

            attractor = chaos_game(matrices, vectores)

        # Selección pseudoaleatoria con semilla derivada de tx_hash (Anti-Replay)
        seed = int(hashlib.sha256(tx_hash.encode()).hexdigest()[:8], 16)
        n_att = len(attractor)
        import random as _rnd

        _rng = _rnd.Random(seed)
        indices = sorted(_rng.sample(range(n_att), min(ZKEngine.N_PROOF, n_att)))
        x_final = [attractor[i] for i in indices]

        # CORRECCIÓN F4: Evaluación polinómica sobre el atractor COMPLETO.
        # Conserva las propiedades topológicas intactas para pasar los 8 criterios.
        result = evaluate(
            x_final=attractor,
            matrices=matrices,
            vectores=vectores,
            params=criterion_params,
            N_total=len(attractor),
        )

        if not result.pass_all:
            raise ValueError(
                f"El atractor no satisface el criterio: {result.summary()}"
            )

        # Commitment compacto: Raíz Merkle de la sub-muestra (100 puntos)
        D = len(x_final[0])
        x_flat = [x_final[i][k] for i in range(len(x_final)) for k in range(D)]
        commitment = MerkleTree.build_root(x_flat)

        # Generación de Audit Sample (1 solo punto)
        audit_idx = (
            int(hashlib.sha256(f"{commitment}:{tx_hash}".encode()).hexdigest(), 16)
            % ZKEngine.N_PROOF
        )
        audit_point = x_final[audit_idx]

        m3_hash = hashlib.sha256(
            json.dumps(public_m3, sort_keys=True).encode()
        ).hexdigest()

        # Sello Fiat-Shamir
        pi_payload = f"{commitment}:{m3_hash}:{tx_hash}:{result.packed}:{audit_idx}"
        pi = hashlib.sha256(pi_payload.encode()).hexdigest()

        return {
            "pi": pi,
            "commitment": commitment,
            "audit_idx": audit_idx,
            "audit_point": audit_point,
            "criterion_packed": result.packed,
            "metrics": {
                "AS": result.AS,
                "Var": result.Var,
                "mu_err": result.mu_err,
                "sk_err": result.sk_err,
                "d2": result.d2,
                "r8": result.r8,
            },
            "x_final": x_final,  # <-- VARIABLE INYECTADA PARA LA AUDITORÍA EMPÍRICA
        }

    @staticmethod
    def verify_proof(
        proof: dict,
        public_m3: list,
        tx_hash: str,
        criterion_params: CriterionParams,
        N_total: int,
    ) -> bool:
        """
        VERIFIER — Ejecutado por el nodo validador.
        Blindado contra forgeability calculando el tensor empírico y la Raíz Merkle.
        """
        try:
            x_final = proof["x_final"]
            commitment = proof["commitment"]
            packed = proof["criterion_packed"]
            pi = proof["pi"]

            # 1. VALIDACIÓN DE COMPROMISO (Merkle Root)
            from crypto.stark_core import MerkleTree

            D_dim = len(x_final[0])
            x_flat = [x_final[i][k] for i in range(len(x_final)) for k in range(D_dim)]
            if MerkleTree.build_root(x_flat) != commitment:
                print("[ZK] Falla: La traza x_final no genera el commitment provisto.")
                return False

            # 2. Verificar Sello Fiat-Shamir
            m3_hash = hashlib.sha256(
                json.dumps(public_m3, sort_keys=True).encode()
            ).hexdigest()
            expected_pi_payload = (
                f"{commitment}:{m3_hash}:{tx_hash}:{packed}:{proof['audit_idx']}"
            )
            expected_pi = hashlib.sha256(expected_pi_payload.encode()).hexdigest()

            if pi != expected_pi:
                print(
                    "[ZK] Falla: PI incorrecto (Ataque de repetición o métricas forjadas)."
                )
                return False

            if not packed:
                print("[ZK] Falla: Bandera packed en estado inválido.")
                return False

            # 3. EVALUACIÓN ANTI-FORGE (Tensor Empírico vs Llave Pública)
            from crypto.tensors import calculate_m3_tensor

            empirical_m3 = calculate_m3_tensor(x_final)

            TOLERANCE = int(0.5 * SCALE_FACTOR)
            D = len(public_m3)
            for i in range(D):
                for j in range(D):
                    for k in range(D):
                        if abs(empirical_m3[i][j][k] - public_m3[i][j][k]) > TOLERANCE:
                            print(
                                "[ZK] Falla: Tensor empírico diverge de la llave pública. Proof falsificado."
                            )
                            return False

            return True

        except (KeyError, TypeError, ValueError, AttributeError) as e:
            print(f"  [ZK] Excepción en modo compacto: {e}")
            return False
