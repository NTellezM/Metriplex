import asyncio
import hashlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from blockchain.block import Block
from core.verifier import CriterionParams
from network.miner import AutoMiner
from network.p2p import CAFNode


class Writer:
    def __init__(self):
        self.data = b""

    def write(self, data):
        self.data += data

    async def drain(self):
        pass

    def close(self):
        pass

    async def wait_closed(self):
        pass


class RestartTests(unittest.IsolatedAsyncioTestCase):
    def make_node(self):
        chain = [Block(0, [], "0", timestamp=1)]
        registry = SimpleNamespace(validators={})
        bc = SimpleNamespace(chain=chain, validator_registry=registry)
        def add(block, **kwargs):
            if block.index != chain[-1].index + 1 or block.previous_hash != chain[-1].hash:
                return False
            chain.append(block)
            return True
        bc.add_block = Mock(side_effect=add)
        return CAFNode("127.0.0.1", 65432, bc, SimpleNamespace(remove_mined_transactions=Mock()))

    async def deliver(self, node, payload):
        reader = asyncio.StreamReader()
        reader.feed_data(json.dumps(payload).encode())
        reader.feed_eof()
        writer = Writer()
        await node.handle_client(reader, writer)
        return writer

    async def test_geo_preserves_cached_attractor_and_params(self):
        node = self.make_node()
        params = CriterionParams(1, 2, [0]*4, 3, 4, 5, 6)
        att = [[0]*4]*400
        node.geo_identity = dict(private_key={"A": [], "b": []}, public_m3=[1],
                                 criterion_params=vars(params), attractor=att)
        with patch("crypto.zkp.ZKEngine.generate_proof", return_value={"pi": "test"}) as gen, \
             patch("crypto.zkp.ZKEngine.verify_proof", return_value=True):
            await node._compute_geo_proof()
        self.assertIs(gen.call_args.kwargs["attractor"], att)
        self.assertEqual(gen.call_args.kwargs["N_total"], 400)
        self.assertEqual(node.geo_proof["criterion_params"], vars(params))

    async def test_geo_upgrades_observer_and_rejects_wrong_identity(self):
        node = self.make_node()
        peer = "5.78.209.5:65436"
        node.peers.add(peer)
        node.observer_peers.add(peer)
        with patch.object(node, "_verify_geo_handshake", return_value=True):
            await self.deliver(node, dict(type="GEO_HANDSHAKE", endpoint=peer, m3_hash="abc", m3=[1]))
        self.assertIn(peer, node.authenticated_peers)
        self.assertNotIn(peer, node.observer_peers)
        self.assertFalse(node._verify_geo_handshake(dict(m3=[1], nonce="n", zk_proof={"x": 1}, m3_hash="wrong")))

    async def test_new_block_is_not_lost_while_syncing(self):
        node = self.make_node()
        node.syncing = True
        block = Block(1, [], node.blockchain.chain[-1].hash, timestamp=2)
        await self.deliver(node, dict(type="NEW_BLOCK", data=block.to_dict()))
        self.assertEqual(node.blockchain.chain[-1].hash, block.hash)
        await self.deliver(node, dict(type="NEW_BLOCK", data=block.to_dict()))
        self.assertEqual(node.blockchain.add_block.call_count, 1)

    async def test_sync_requests_last_missing_block(self):
        node = self.make_node()
        node._broadcast = AsyncMock()
        block = Block(1, [], node.blockchain.chain[-1].hash, timestamp=2)
        await self.deliver(node, dict(type="CHAIN_SEGMENT", blocks=[block.to_dict()], peer_height=2))
        self.assertEqual(node.sync_target, 2)
        request = json.loads(node._broadcast.call_args.args[0])
        self.assertEqual(request["last_index"], 1)

    async def test_epoch_uses_timestamp_and_same_historical_fvr(self):
        slot = 29814520
        cutoff = (slot // 100 - 1) * 100 * 60
        shared = [Block(0, [], "0", 1), Block(1, [], "x", cutoff-1)]
        registry = SimpleNamespace(get_validators_at=Mock(return_value=[{"m3_hash": "a"}]))
        results = []
        for tip_time in (cutoff+1, cutoff+70):
            bc = SimpleNamespace(chain=shared+[Block(2, [], "y", tip_time)], validator_registry=registry)
            miner = AutoMiner(bc, None, None, block_time_seconds=60)
            results.append(miner._election_context(slot))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0][0].index, 1)
        registry.get_validators_at.assert_called_with(1)


if __name__ == "__main__":
    unittest.main()
