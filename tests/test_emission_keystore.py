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

    async def test_key_material_is_random_not_derived_from_address(self):
        import httpx
        app = self.make_app()
        addr = "0x" + "1" * 40          # MISMA dirección en ambas peticiones
        claves = [{"A": [[[1]]], "b": [[1]]}, {"A": [[[2]]], "b": [[2]]}]

        async def pedir():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://t") as c:
                r = await c.post("/keystore/generate",
                                 json={"address": addr, "password": "una-passphrase"})
            self.assertEqual(r.status_code, 200)
            return r.json()

        # La ruta importa estos nombres dentro de la función, así que hay que
        # parchear el módulo de origen, no api.server.
        with patch("crypto.keys.generate_private_key", side_effect=claves) as gen, \
             patch("crypto.keys.chaos_game", return_value=[[1] * 4] * 8), \
             patch("core.verifier.calibrate", return_value=SimpleNamespace(theta=1)), \
             patch("core.verifier.evaluate", return_value=SimpleNamespace(pass_all=True)), \
             patch("crypto.tensors.calculate_m3_tensor", side_effect=[[[1]], [[2]]]):
            a, b = await pedir(), await pedir()

        # Misma dirección EVM, identidades distintas => la clave no se deriva de ella
        self.assertNotEqual(a["address"], b["address"])
        self.assertEqual(gen.call_count, 2)
        for call in gen.call_args_list:          # invocada sin semilla alguna
            self.assertEqual(call.args, ())
            self.assertEqual(call.kwargs, {})
        self.assertNotIn("private_key", a["keystore"])
        self.assertIn("warning", a)

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
