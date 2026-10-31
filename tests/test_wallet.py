"""Wallet tests. Offline: the RPC is faked, the key is a fresh throwaway made per test.

Run from the repo root with the venv:
    .venv/bin/python -m unittest discover -s tests -v
"""
import contextlib
import io
import os
import re
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import wallet  # noqa: E402

try:
    from eth_account import Account
    from eth_account.typed_transactions import TypedTransaction
    from eth_utils import keccak
    from hexbytes import HexBytes
except ImportError:
    Account = None

TO = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"
GWEI = 10 ** 9
FAILURE_FREE_OF_KEY = "SendError text must never contain the key"


class FakeRpc:
    """Replaces wallet._rpc. Values that are exceptions are raised."""

    def __init__(self, **over):
        self.calls = []
        self.state = {
            "eth_chainId": hex(wallet.SEPOLIA), "eth_getTransactionCount": "0x7",
            "eth_getBlockByNumber": {"baseFeePerGas": hex(GWEI)}, "eth_maxPriorityFeePerGas": hex(GWEI),
            "eth_estimateGas": hex(21000), "eth_getBalance": hex(10 ** 18), "eth_sendRawTransaction": "0xok"}
        self.state.update(over)

    def __call__(self, url, method, params):
        self.calls.append((method, params))
        value = self.state[method]
        if isinstance(value, Exception):
            raise value
        return value

    def methods(self):
        return [m for m, _ in self.calls]

    def raw(self):
        return next(p[0] for m, p in self.calls if m == "eth_sendRawTransaction")


@unittest.skipUnless(Account, "eth-account not installed")
class SendTests(unittest.TestCase):
    def setUp(self):
        self.account = Account.create()
        self.key = "0x" + bytes(self.account.key).hex()
        env = {"SEPOLIA_PRIVATE_KEY": self.key, "SEPOLIA_RPC_URL": "http://rpc.invalid"}
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def rpc(self, **over):
        fake = FakeRpc(**over)
        patcher = mock.patch.object(wallet, "_rpc", fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    def assert_send_error(self, *args, calls_ok=True, **kw):
        with self.assertRaises(wallet.SendError) as ctx:
            wallet.send_eth(*args, **kw)
        text = str(ctx.exception)
        self.assertNotIn(self.key, text)
        self.assertNotIn(self.key[2:], text)
        return ctx.exception

    def test_signed_transaction_is_what_was_asked_for(self):
        rpc = self.rpc()
        tx_hash = wallet.send_eth(TO.lower(), 10 ** 16)
        raw = rpc.raw()
        self.assertEqual(rpc.calls[0][0], "eth_chainId")                  # chain is checked first
        self.assertEqual(rpc.methods().count("eth_sendRawTransaction"), 1)
        self.assertEqual(Account.recover_transaction(raw), self.account.address)
        tx = TypedTransaction.from_bytes(HexBytes(raw)).as_dict()
        self.assertEqual("0x" + bytes(tx["to"]).hex(), TO.lower())
        self.assertEqual((tx["value"], tx["chainId"], tx["nonce"]), (10 ** 16, wallet.SEPOLIA, 7))
        self.assertEqual(tx["gas"], 25200)                               # estimate 21000 + 20%
        self.assertEqual(tx["maxPriorityFeePerGas"], GWEI)
        self.assertEqual(tx["maxFeePerGas"], 2 * GWEI + GWEI)
        self.assertEqual(tx_hash, "0x" + keccak(HexBytes(raw)).hex())
        nonce_call = next(p for m, p in rpc.calls if m == "eth_getTransactionCount")
        self.assertEqual(nonce_call, [self.account.address, "pending"])  # queued transactions count

    def test_wrong_chain_sends_nothing(self):
        for chain in (hex(1), hex(8453), "0x0"):
            rpc = self.rpc(eth_chainId=chain)
            error = self.assert_send_error(TO, 10 ** 16)
            self.assertIn("not Sepolia", str(error))
            self.assertEqual(rpc.methods(), ["eth_chainId"])

    def test_bad_arguments_never_touch_the_network(self):
        rpc = self.rpc()
        for args in ((TO, 0), (TO, -1), (TO, 10 ** 16 + 1), (TO, True), (TO, 1.5), (TO, "1"), (TO, None),
                     ("0x123", 1), ("", 1), (TO + "00", 1), (None, 1), (TO, 1, 1), (TO, 1, 0), (TO, 1, 8453)):
            self.assert_send_error(*args)
        self.assertEqual(rpc.calls, [])
        for bad_address in ("0x123", "", TO + "00", None):
            self.assertIn("address is not valid", str(self.assert_send_error(bad_address, 1)))

    def test_the_cap_follows_the_environment(self):
        rpc = self.rpc()
        with mock.patch.dict(os.environ, {"WARDEN_MAX_ETH": "0.001"}):
            self.assert_send_error(TO, 10 ** 16)
            wallet.send_eth(TO, 10 ** 15)
        self.assertEqual(rpc.methods().count("eth_sendRawTransaction"), 1)

    def test_missing_or_bad_key(self):
        rpc = self.rpc()
        with mock.patch.dict(os.environ, {"SEPOLIA_PRIVATE_KEY": ""}):
            self.assertIn("not set up", str(self.assert_send_error(TO, 1)))
        for bad in ("0x12", "not a key", "0x" + "zz" * 32):
            with mock.patch.dict(os.environ, {"SEPOLIA_PRIVATE_KEY": bad}):
                error = self.assert_send_error(TO, 1)
                self.assertIn("not valid", str(error))
                self.assertNotIn(bad, str(error))
        self.assertEqual(rpc.calls, [])

    def test_failures_before_the_broadcast_send_nothing(self):
        cases = {
            "too little": dict(eth_getBalance=hex(10)),
            "would fail": dict(eth_estimateGas=RuntimeError("execution reverted")),
            "could not reach (os)": dict(eth_getTransactionCount=OSError("down")),
            "could not reach (json)": dict(eth_getBlockByNumber=ValueError("garbage")),
            "could not reach (shape)": dict(eth_getBlockByNumber={}),
        }
        for expect, over in cases.items():
            rpc = self.rpc(**over)
            error = self.assert_send_error(TO, 10 ** 16)
            self.assertIn(expect.split(" (")[0], str(error), expect)
            self.assertIsNone(error.tx_hash, expect)
            self.assertNotIn("eth_sendRawTransaction", rpc.methods(), expect)

    def test_node_refusal_means_not_sent(self):
        self.rpc(eth_sendRawTransaction=RuntimeError("nonce too low"))
        error = self.assert_send_error(TO, 10 ** 16)
        self.assertIn("nonce too low", str(error))
        self.assertIsNone(error.tx_hash)

    def test_silence_after_the_broadcast_may_mean_sent(self):
        for failure in (OSError("timed out"), ValueError("garbled")):
            rpc = self.rpc(eth_sendRawTransaction=failure)
            error = self.assert_send_error(TO, 10 ** 16)
            self.assertRegex(error.tx_hash, r"0x[0-9a-f]{64}")
            self.assertEqual(error.tx_hash, "0x" + keccak(HexBytes(rpc.raw())).hex())

    def test_fee_handling(self):
        rpc = self.rpc(eth_maxPriorityFeePerGas=RuntimeError("unsupported"))
        wallet.send_eth(TO, 1)
        tx = TypedTransaction.from_bytes(HexBytes(rpc.raw())).as_dict()
        self.assertEqual(tx["maxPriorityFeePerGas"], 3 * GWEI // 2)
        rpc = self.rpc(eth_maxPriorityFeePerGas=hex(1))                  # a 1 wei tip would stall
        wallet.send_eth(TO, 1)
        tx = TypedTransaction.from_bytes(HexBytes(rpc.raw())).as_dict()
        self.assertEqual(tx["maxPriorityFeePerGas"], GWEI)

    def test_balance_must_cover_amount_and_gas(self):
        amount = 10 ** 16
        gas_cost = 25200 * 3 * GWEI
        self.rpc(eth_getBalance=hex(amount + gas_cost - 1))
        self.assert_send_error(TO, amount)
        rpc = self.rpc(eth_getBalance=hex(amount + gas_cost))
        wallet.send_eth(TO, amount)
        self.assertIn("eth_sendRawTransaction", rpc.methods())


class ConfigTests(unittest.TestCase):
    def test_max_wei(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(wallet.max_wei(), 10 ** 16)
        for value, expect in (("0.5", 5 * 10 ** 17), ("1e-3", 10 ** 15), ("abc", 10 ** 16), ("-1", 10 ** 16),
                              ("0", 10 ** 16), ("nan", 10 ** 16), ("inf", 10 ** 16), ("", 10 ** 16)):
            with mock.patch.dict(os.environ, {"WARDEN_MAX_ETH": value}, clear=True):
                self.assertEqual(wallet.max_wei(), expect, value)

    def test_format_eth(self):
        for wei, text in ((10 ** 16, "0.01"), (10 ** 18, "1"), (1, "0.000000000000000001"),
                          (123456789 * 10 ** 9, "0.123456789"), (5 * 10 ** 15, "0.005")):
            self.assertEqual(wallet.format_eth(wei), text)

    def test_rpc_url(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(wallet.rpc_url(), wallet.DEFAULT_RPC)
        with mock.patch.dict(os.environ, {"SEPOLIA_RPC_URL": "https://my.rpc/x"}, clear=True):
            self.assertEqual(wallet.rpc_url(), "https://my.rpc/x")
        for bad in ("file:///etc/passwd", "ftp://x", "my.rpc"):
            with mock.patch.dict(os.environ, {"SEPOLIA_RPC_URL": bad}, clear=True):
                with self.assertRaises(wallet.SendError):
                    wallet.rpc_url()

    def test_load_env_never_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("# comment\nA_ONE=1\nA_TWO='two'\n\nA_THREE = \"3\"\nbroken line\nA_SET=file\n")
            with mock.patch.dict(os.environ, {"A_SET": "shell"}, clear=True):
                wallet.load_env(path)
                self.assertEqual((os.environ["A_ONE"], os.environ["A_TWO"], os.environ["A_THREE"]), ("1", "two", "3"))
                self.assertEqual(os.environ["A_SET"], "shell")
            wallet.load_env(Path(tmp) / "missing.env")                   # no file is fine


@unittest.skipUnless(Account, "eth-account not installed")
class CliTests(unittest.TestCase):
    def run_cli(self, argv, env=None):
        out = io.StringIO()
        with mock.patch.dict(os.environ, env or {}, clear=True), contextlib.redirect_stdout(out), \
                mock.patch.object(wallet, "load_env"):
            code = wallet.main(argv)
        return code, out.getvalue()

    def test_new_wallet_saves_the_key_and_prints_only_the_address(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("ANTHROPIC_API_KEY=keep-me")                 # no trailing newline
            with mock.patch.object(wallet, "ENV_PATH", path):
                code, out = self.run_cli(["new-wallet"])
                text = path.read_text()
                self.assertEqual(code, 0)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertTrue(text.startswith("ANTHROPIC_API_KEY=keep-me\nSEPOLIA_PRIVATE_KEY=0x"))
                key = re.search(r"SEPOLIA_PRIVATE_KEY=(0x[0-9a-f]{64})\n", text).group(1)
                address = re.search(r"0x[0-9a-fA-F]{40}", out).group(0)
                self.assertEqual(Account.from_key(key).address, address)
                self.assertNotIn(key, out)
                self.assertNotIn(key[2:], out)
                code, out = self.run_cli(["new-wallet"], env={"SEPOLIA_PRIVATE_KEY": key})  # never overwrite
                self.assertEqual(code, 1)
                self.assertEqual(path.read_text(), text)

    def test_address_command_prints_no_key(self):
        account = Account.create()
        key = "0x" + bytes(account.key).hex()
        code, out = self.run_cli(["address"], env={"SEPOLIA_PRIVATE_KEY": key})
        self.assertEqual((code, out.strip()), (0, account.address))

    def test_unknown_command(self):
        self.assertEqual(self.run_cli(["bogus"])[0], 2)
        self.assertEqual(self.run_cli([])[0], 2)


if __name__ == "__main__":
    unittest.main()
