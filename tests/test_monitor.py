import copy
import io
import json
import os
import unittest
from unittest.mock import patch
import metriplex_monitor as monitor


class MonitorTests(unittest.TestCase):
    def healthy(self):
        data = {n: {"chain_length": 10, "latest_block_hash": "a" * 64} for n in monitor.NODES}
        data.update(now=10000, services={s: "active" for s in monitor.SERVICES},
                    validators={"count": 4, "validators": [{"endpoint": "5.78.209.5:65436"}]},
                    block=[{"timestamp": 9950}], network={"nodes": {"local": {"online": True},
                         "5.78.209.5:65436": {"online": True}}}, vault={"balance_caf": 20000},
                    journal_rc=0, journal="9900 host [GEO] Proof precomputado. Válido 1h.\n"
                    "9990 host [GEO] Peer autenticado (validador): 5.78.209.5:65436")
        return data

    def test_healthy_and_real_slot_threshold(self):
        issues, _, summary = monitor.analyze(self.healthy(), {})
        self.assertEqual(issues, {})
        self.assertEqual(summary["max_block_age_seconds"], 1200)

    def test_lag_confirmed_deduplicated_and_recovered(self):
        data = self.healthy()
        data["node-NT"]["chain_length"] = 9
        issues, _, _ = monitor.analyze(data, {})
        first, text = monitor.transition(issues, {}, 1)
        self.assertEqual(text, "")
        second, text = monitor.transition(issues, first, 2)
        self.assertIn("retraso", text)
        third, text = monitor.transition(issues, second, 3)
        self.assertEqual(text, "")
        recovered, text = monitor.transition({}, third, 4)
        self.assertIn("resueltas", text)
        self.assertEqual(recovered["active"], {})

    def test_same_height_fork_and_geo_failure(self):
        data = self.healthy()
        data["node-3"]["latest_block_hash"] = "b"*64
        data["journal"] += "\n9999 host [GEO] Error computando proof: c8"
        issues, _, _ = monitor.analyze(data, {})
        self.assertIn("fork:node-0:node-3", issues)
        self.assertIn("geo:local", issues)

    def test_fork_wording_and_age_filter(self):
        data = self.healthy()
        data["journal"] += "\n" + "\n".join("9999 host Conflicto de bifurcación detectado" for _ in range(4))
        issues, _, _ = monitor.analyze(data, {})
        self.assertIn("forks:frequent", issues)
        data["journal"] = data["journal"].replace("9999", "9000")
        self.assertNotIn("forks:frequent", monitor.analyze(data, {})[0])

    def test_failed_queries_are_not_isolation_or_recovery(self):
        data = self.healthy()
        data["network"] = None
        data["vault"] = None
        data["node-3"] = None
        issues, _, _ = monitor.analyze(data, {"vault": 20000})
        self.assertNotIn("peers:isolated", issues)
        self.assertNotIn("vault:drop", issues)
        state, text = monitor.transition(issues, {"active": {"lag:node-3": "old lag"}}, 1)
        self.assertIn("lag:node-3", state["active"])
        self.assertNotIn("resueltas", text)

    def test_vault_drop_persists_until_balance_recovers(self):
        data = self.healthy()
        data["vault"]["balance_caf"] = 8000
        issues, baseline, _ = monitor.analyze(data, {"vault": 20000})
        self.assertIn("vault:drop", issues)
        self.assertIn("vault:drop", monitor.analyze(data, baseline)[0])
        data["vault"]["balance_caf"] = 20000
        self.assertNotIn("vault:drop", monitor.analyze(data, baseline)[0])

    def test_telegram_rejection_and_timeout_hide_token(self):
        with patch.dict(os.environ, BOT_TOKEN="SECRET", CHAT_ID="PRIVATE"), \
             patch("urllib.request.urlopen", side_effect=OSError("url with SECRET")), \
             patch("sys.stderr", new_callable=io.StringIO) as stderr:
            self.assertFalse(monitor.send_alert("test"))
            self.assertNotIn("SECRET", stderr.getvalue())
        with patch.dict(os.environ, BOT_TOKEN="SECRET", CHAT_ID="PRIVATE"), \
             patch("urllib.request.urlopen") as request:
            request.return_value.__enter__.return_value = io.StringIO('{"ok":false}')
            self.assertFalse(monitor.send_alert("test"))
            self.assertEqual(request.call_args.kwargs["timeout"], 12)

    def test_dry_run_never_sends_or_writes_state(self):
        with patch("sys.argv", ["monitor", "--dry-run"]), \
             patch.object(monitor, "collect", return_value=self.healthy()), \
             patch.object(monitor, "send_alert") as send, \
             patch("pathlib.Path.read_text", side_effect=FileNotFoundError), \
             patch("pathlib.Path.open") as write, patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(monitor.main(), 0)
            send.assert_not_called()
            write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
