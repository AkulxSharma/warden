"""Wallet dashboard data tests. No network: RPC and Etherscan are mocked.

Run from sessions/warden:
    PATH="$PWD/.venv/bin:$PATH" python3 -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import chain  # noqa: E402
import etherscan  # noqa: E402
import server  # noqa: E402
import wallets  # noqa: E402

A = "0x" + "aa" * 20
B = "0x" + "bb" * 20
WALLETS = [{"alias": "andrew.eth", "role": "Agent wallet (sender)", "address": A},
           {"alias": "akul.eth", "role": "Receiver", "address": B}]


def tx(h, frm, to, value, ts, err="0"):
    return {"hash": h, "from": frm, "to": to, "value": str(value), "timeStamp": str(ts), "isError": err}


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        # never read the real bot events log from a test
        patcher = mock.patch.object(wallets, "EVENTS_DEFAULT", Path("/nonexistent/events.jsonl"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def snap(self, txs_by_address, balance_hex="0x2ea11e32ad50000", **kw):
        with mock.patch.object(chain, "call", return_value=balance_hex), \
                mock.patch.object(wallets, "recent_txs", side_effect=lambda a, k, n: txs_by_address.get(a, [])):
            return wallets.snapshot(api_key="k", wallets=WALLETS, **kw)

    def test_eth_formatting(self):
        self.assertEqual(wallets.eth(210000000000000000), "0.210000")
        self.assertEqual(wallets.eth(0), "0.000000")

    def test_balances_and_aliases(self):
        out = self.snap({})
        self.assertEqual([w["alias"] for w in out["wallets"]], ["andrew.eth", "akul.eth"])
        self.assertEqual(out["wallets"][0]["balanceEth"], "0.210000")
        self.assertTrue(out["wallets"][0]["explorer"].endswith(A))
        self.assertIsNone(out["transfersError"])

    def test_transfers_deduped_sorted_labelled_and_zero_value_dropped(self):
        shared = tx("0x1", A, B, 10**15, 200)
        out = self.snap({A: [shared, tx("0x2", A, "0x" + "cc" * 20, 0, 150), tx("0x3", B, A, 5 * 10**15, 100, err="1")],
                         B: [shared]})
        hashes = [t["hash"] for t in out["transfers"]]
        self.assertEqual(hashes, ["0x1", "0x3"])  # newest first, duplicate and zero-value dropped
        first = out["transfers"][0]
        self.assertEqual((first["fromAlias"], first["toAlias"], first["valueEth"], first["status"]),
                         ("andrew.eth", "akul.eth", "0.001000", "confirmed"))
        self.assertEqual(out["transfers"][1]["status"], "failed")

    def test_reverted_topup_of_a_demo_target_is_hidden_but_other_failures_show(self):
        target = "0x" + "99" * 20
        wl = WALLETS + [{"alias": "vault.eth", "role": "t", "address": target, "kind": "target"}]
        txs = {A: [tx("0xf1", A, target, 10**15, 300, err="1"), tx("0xf2", A, B, 10**15, 200, err="1")]}
        with mock.patch.object(chain, "call", return_value="0x0"), \
                mock.patch.object(wallets, "recent_txs", side_effect=lambda a, k, n: txs.get(a, [])):
            out = wallets.snapshot(api_key="k", wallets=wl)
        self.assertEqual([t["hash"] for t in out["transfers"]], ["0xf2"])

    def test_unknown_counterparty_has_no_alias(self):
        other = "0x" + "dd" * 20
        out = self.snap({A: [tx("0x4", other, A, 10**15, 100)]})
        self.assertIsNone(out["transfers"][0]["fromAlias"])
        self.assertEqual(out["transfers"][0]["toAlias"], "andrew.eth")

    def test_etherscan_failure_keeps_balances(self):
        with mock.patch.object(chain, "call", return_value="0x0"), \
                mock.patch.object(wallets, "recent_txs", side_effect=etherscan.EtherscanError("rate")):
            out = wallets.snapshot(api_key="k", wallets=WALLETS)
        self.assertEqual(len(out["wallets"]), 2)
        self.assertEqual(out["transfers"], [])
        self.assertIn("rate", out["transfersError"])

    def test_no_key_keeps_balances(self):
        with mock.patch.dict("os.environ", {}, clear=True), mock.patch.object(chain, "call", return_value="0x0"):
            out = wallets.snapshot(wallets=WALLETS)
        self.assertEqual(out["transfers"], [])
        self.assertIn("key", out["transfersError"])

    def test_wallets_json_is_valid(self):
        for w in wallets.load_wallets():
            self.assertRegex(w["address"], r"^0x[0-9a-fA-F]{40}$")
            self.assertTrue(w["alias"].endswith(".eth"))


class BlockedAttemptTests(unittest.TestCase):
    TARGET = "0x" + "ee" * 20

    def write_events(self, events):
        import json
        import tempfile
        path = Path(tempfile.mkdtemp()) / "events.jsonl"
        path.write_text("\n".join(json.dumps(e) for e in events) + "\nnot json\n")
        return path

    def refused(self, ts, text="send 0.001 to drainer.eth"):
        return {"ts": ts, "kind": "refused", "text": text,
                "result": {"target": self.TARGET, "verdict": "HIGH", "riskScore": 65,
                           "findings": [{"id": "selfdestruct-opcode", "severity": "high",
                                         "message": "bytecode contains a SELFDESTRUCT opcode"}]}}

    def test_only_refused_events_become_blocked_attempts(self):
        path = self.write_events([{"ts": 1, "kind": "confirm", "text": "send 0.001 to akul.eth"},
                                  self.refused(2), {"ts": 3, "kind": "text", "text": "hello"}])
        out = wallets.blocked_attempts(WALLETS, path)
        self.assertEqual(len(out), 1)
        b = out[0]
        self.assertEqual((b["status"], b["fromAlias"], b["valueEth"], b["time"]),
                         ("blocked", "andrew.eth", "0.001", 2))
        self.assertIsNone(b["hash"])
        self.assertIsNone(b["explorer"])  # it never reached the chain: no proof link
        self.assertIn("HIGH risk (65/100)", b["reason"])
        self.assertIn("SELFDESTRUCT", b["reason"])

    def test_target_alias_resolved_from_wallet_list(self):
        wallets_with_target = WALLETS + [{"alias": "drainer.eth", "role": "target", "address": self.TARGET}]
        path = self.write_events([self.refused(5)])
        self.assertEqual(wallets.blocked_attempts(wallets_with_target, path)[0]["toAlias"], "drainer.eth")

    def test_refusal_when_check_could_not_run(self):
        path = self.write_events([{"ts": 9, "kind": "refused", "text": "send 0.01 to 0x" + "11" * 20, "result": None}])
        b = wallets.blocked_attempts(WALLETS, path)[0]
        self.assertIn("could not run", b["reason"])
        self.assertIsNone(b["to"])

    def test_missing_log_gives_no_blocked_attempts(self):
        self.assertEqual(wallets.blocked_attempts(WALLETS, "/nonexistent/events.jsonl"), [])

    def test_blocked_rows_merge_with_on_chain_transfers_newest_first(self):
        path = self.write_events([self.refused(150)])
        with mock.patch.object(chain, "call", return_value="0x0"), \
                mock.patch.object(wallets, "recent_txs",
                                  side_effect=lambda a, k, n: [tx("0x1", A, B, 10**15, 200), tx("0x2", A, B, 10**15, 100)]
                                  if a == A else []):
            out = wallets.snapshot(api_key="k", wallets=WALLETS, events_path=path)
        self.assertEqual([t["status"] for t in out["transfers"]], ["confirmed", "blocked", "confirmed"])


class DashboardPageTests(unittest.TestCase):
    def test_page_reads_wallets_and_never_uses_innerhtml(self):
        html = (ROOT / "dashboard.html").read_text()
        self.assertIn("/wallets", html)
        self.assertNotIn("innerHTML", html)  # all dynamic text goes through textContent


class ServerWalletRouteTests(unittest.TestCase):
    def setUp(self):
        server.reset()

    def test_wallets_route_ok_and_cached(self):
        snap = {"chainId": 11155111, "wallets": [], "transfers": [], "transfersError": None}
        with mock.patch.object(wallets, "snapshot", return_value=snap) as m:
            self.assertEqual(server.handle("/wallets", now=1000), (200, snap))
            server.handle("/wallets", now=1001)
        self.assertEqual(m.call_count, 1)

    def test_wallets_route_502_on_chain_failure(self):
        with mock.patch.object(wallets, "snapshot", side_effect=chain.ChainError("down")):
            self.assertEqual(server.handle("/wallets", now=1000)[0], 502)


if __name__ == "__main__":
    unittest.main()
