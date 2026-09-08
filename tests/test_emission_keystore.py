"""
Regresiones de emisión y de generación de keystore (2026-09-08).

Emisión: R₀ usaba SCALE_FACTOR (conversión raw↔MPX) como si fuera una
constante económica. Con Supply(∞) = R₀·T_scale/|λ_mean|, tanto |λ_mean| como
T_scale se cancelaban y el techo quedaba en 2**30 raw = 1 MPX, pagando ~2.4e-8
MPX por bloque. La cadena llegó a pagar 1.110 MPX/bloque; ese valor ancla el test.

Keystore: la clave privada salía de RandomState(sha256(evm_address)[:4]), o sea
reproducible desde un dato público y con espacio real de 2**31.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.arithmetic import SCALE_FACTOR
from network.miner import AutoMiner


class EmissionTests(unittest.TestCase):
    def r0_mpx(self, lambda_mean):
        return AutoMiner.SUPPLY_PER_LAMBDA * lambda_mean ** 2 / AutoMiner.T_SCALE

    def ceiling_mpx(self, lambda_mean):
        # Supply(∞) = R₀ · T_scale / |λ_mean|
        return self.r0_mpx(lambda_mean) * AutoMiner.T_SCALE / abs(lambda_mean)

    def test_calibration_lambda_yields_target_supply(self):
        self.assertAlmostEqual(
            self.ceiling_mpx(AutoMiner.LAMBDA_MEAN_INIT),
            AutoMiner.TARGET_SUPPLY_MPX, delta=1.0)

    def test_reproduces_historical_onchain_reward(self):
        # 252 bloques pagaron 1.11 MPX a node-2, cuyo territorio era 60.34%
        r0 = self.r0_mpx(AutoMiner.LAMBDA_MEAN_INIT)
        self.assertAlmostEqual(r0, 1.8389, places=3)
        self.assertAlmostEqual(r0 * 0.6034, 1.110, places=3)

    def test_ceiling_grows_with_geometric_diversity(self):
        # La propiedad que el whitepaper documenta: más diversidad (|λ_mean|
        # mayor) => mayor techo. Antes el techo era constante = 1 MPX.
        low, high = self.ceiling_mpx(-0.4), self.ceiling_mpx(-0.9)
        self.assertLess(low, high)
        self.assertAlmostEqual(high / low, 0.9 / 0.4, places=6)

    def test_reward_is_not_dust(self):
        # Regresión directa: la fórmula vieja daba < 1e-6 MPX por bloque.
        old_r0_raw = abs(-0.667505) / AutoMiner.T_SCALE * SCALE_FACTOR
        new_r0_raw = self.r0_mpx(-0.667505) * SCALE_FACTOR
        self.assertLess(old_r0_raw / SCALE_FACTOR, 1e-6)
        self.assertGreater(new_r0_raw / SCALE_FACTOR, 2.0)

    def test_voronoi_split_sums_to_base_emission(self):
        # Territorios exactos desde los λ on-chain, no redondeados.
        import math
        lmin, lmax = math.log(0.30), math.log(0.70)
        lambdas = sorted([-0.4702245262221796, -0.6993205261890453,
                          -0.6860353316667722, -0.814437968568363])
        edges = [lmin] + [(a + b) / 2 for a, b in zip(lambdas, lambdas[1:])] + [lmax]
        territories = [(hi - lo) / (lmax - lmin) for lo, hi in zip(edges, edges[1:])]
        self.assertAlmostEqual(sum(territories), 1.0, places=12)
        r0 = self.r0_mpx(sum(lambdas) / len(lambdas))
        self.assertAlmostEqual(sum(r0 * t for t in territories), r0, places=9)


class KeystoreTests(unittest.IsolatedAsyncioTestCase):
    def make_app(self):
        from api.server import create_api_app
        chain = SimpleNamespace(chain=[SimpleNamespace(index=1, hash="a" * 64)],
                                validator_registry=SimpleNamespace(validators={}))
        node = SimpleNamespace(host_public="127.0.0.1", port=65432, peers=set(),
                               permanent_peers=set(), authenticated_peers={})
        return create_api_app(chain, SimpleNamespace(pending_transactions={}), node)

    def test_single_route_registered(self):
        paths = [r.path for r in self.make_app().routes]
        self.assertEqual(paths.count("/keystore/generate"), 1)

    async def test_seed_comes_from_system_entropy_not_the_address(self):
        import os as _os
        import httpx
        app = self.make_app()
        addr = "0x" + "1" * 40

        real_urandom = _os.urandom
        seed_sizes = []

        def spy(n):
            seed_sizes.append(n)
            return real_urandom(n)

        with patch("os.urandom", side_effect=spy), \
             patch("crypto.keys._make_contraction_seeded", return_value=[[1]]), \
             patch("crypto.keys.validate_r1", return_value=(True, None)), \
             patch("crypto.keys.validate_scale", return_value=(True, None)), \
             patch("crypto.keys.validate_kruskal", return_value=(True, 4, None)), \
             patch("crypto.keys.chaos_game", return_value=[[1] * 4] * 8), \
             patch("core.verifier.calibrate", return_value=SimpleNamespace(theta=1)), \
             patch("core.verifier.evaluate", return_value=SimpleNamespace(pass_all=True)), \
             patch("crypto.tensors.calculate_m3_tensor", return_value=[[1]]):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://t") as c:
                r = await c.post("/keystore/generate",
                                 json={"address": addr, "password": "una-passphrase"})

        self.assertEqual(r.status_code, 200)
        # 32 bytes = 256 bits para sembrar el RandomState (antes: 31 bits
        # derivados de sha256(evm_address)). El de 16 es el salt de PBKDF2.
        self.assertIn(32, seed_sizes)
        body = r.json()
        self.assertNotIn("private_key", body["keystore"])
        self.assertIn("warning", body)

    def test_route_source_has_no_address_derived_seed(self):
        # Guarda de regresión sobre el patrón exacto que causó el fallo.
        # Mira sólo código: los comentarios mencionan el patrón viejo a propósito.
        import inspect
        import api.server as srv
        src = inspect.getsource(srv.create_api_app)
        i = src.index('@app.post("/keystore/generate")')
        route = src[i:i + 4000]

        code = []
        in_doc = False
        for line in route.splitlines():
            if line.strip().startswith('"""'):
                in_doc = not in_doc
                continue
            if in_doc:
                continue
            code.append(line.split("#", 1)[0])
        code = "\n".join(code)

        self.assertIn("os.urandom(32)", code)
        # La dirección no debe alimentar ninguna semilla ni RNG.
        for line in code.splitlines():
            if "evm_address" in line:
                self.assertNotIn("RandomState", line)
                self.assertNotIn("seed", line.lower())
                self.assertNotIn("sha256", line)

    async def test_rejects_bad_input(self):
        import httpx
        app = self.make_app()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://t") as c:
            for body in ({"address": "0x" + "z" * 40, "password": "una-passphrase"},
                         {"address": "0x" + "1" * 40, "password": "corta"},
                         {"address": None, "password": None}):
                self.assertEqual((await c.post("/keystore/generate", json=body)).status_code, 400)


if __name__ == "__main__":
    unittest.main()
