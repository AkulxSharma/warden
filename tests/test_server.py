"""server.handle() tests. No sockets, no network: auditor.screen is mocked.

Run from sessions/warden:
    PATH="$PWD/.venv/bin:$PATH" python3 -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import auditor  # noqa: E402
import server  # noqa: E402

ADDR = "0x" + "11" * 20
OK_RESULT = auditor.build_result(ADDR, 11155111, [], False)


class HandleTests(unittest.TestCase):
    def setUp(self):
        server.reset()

    def test_identical_requests_are_cached_for_ttl(self):
        with mock.patch.object(auditor, "screen", return_value=OK_RESULT) as m:
            server.handle(f"/screen?address={ADDR}", now=1000)
            server.handle(f"/screen?address={ADDR}", now=1000 + server.CACHE_TTL - 1)
            self.assertEqual(m.call_count, 1)
            server.handle(f"/screen?address={ADDR}", now=1000 + server.CACHE_TTL + 1)
            self.assertEqual(m.call_count, 2)

    def test_failures_are_not_cached(self):
        with mock.patch.object(auditor, "screen", side_effect=auditor.AuditorError("down")) as m:
            self.assertEqual(server.handle(f"/screen?address={ADDR}", now=1000)[0], 502)
            self.assertEqual(server.handle(f"/screen?address={ADDR}", now=1001)[0], 502)
            self.assertEqual(m.call_count, 2)

    def test_cache_key_is_exact_address_so_target_echo_matches(self):
        upper = "0x" + "AB" * 20
        lower = upper.lower()
        with mock.patch.object(auditor, "screen",
                               side_effect=lambda a, c: auditor.build_result(a, c, [], False)):
            first = server.handle(f"/screen?address={upper}", now=1000)[1]
            second = server.handle(f"/screen?address={lower}", now=1001)[1]
        self.assertEqual((first["target"], second["target"]), (upper, lower))

    def test_rate_limit_per_client(self):
        with mock.patch.object(auditor, "screen", return_value=OK_RESULT):
            for i in range(server.RATE_LIMIT):
                self.assertEqual(server.handle(f"/screen?address={ADDR}", client="a", now=1000 + i * 0.1)[0], 200)
            self.assertEqual(server.handle(f"/screen?address={ADDR}", client="a", now=1010)[0], 429)
            self.assertEqual(server.handle(f"/screen?address={ADDR}", client="b", now=1010)[0], 200)

    def test_health_is_never_rate_limited(self):
        for i in range(server.RATE_LIMIT + 5):
            self.assertEqual(server.handle("/health", client="a", now=1000)[0], 200)

    def test_health(self):
        self.assertEqual(server.handle("/health"), (200, {"ok": True}))

    def test_unknown_path_is_404(self):
        self.assertEqual(server.handle("/nope")[0], 404)

    def test_missing_or_bad_address_is_400(self):
        self.assertEqual(server.handle("/screen")[0], 400)
        self.assertEqual(server.handle("/screen?address=0x123")[0], 400)

    def test_bad_chain_id_is_400(self):
        self.assertEqual(server.handle(f"/screen?address={ADDR}&chainId=abc")[0], 400)

    def test_screen_returns_auditor_json(self):
        with mock.patch.object(auditor, "screen", return_value=OK_RESULT) as m:
            status, body = server.handle(f"/screen?address={ADDR}&chainId=11155111")
        self.assertEqual((status, body), (200, OK_RESULT))
        m.assert_called_once_with(ADDR, 11155111)

    def test_chain_id_defaults_to_sepolia(self):
        with mock.patch.object(auditor, "screen", return_value=OK_RESULT) as m:
            server.handle(f"/screen?address={ADDR}")
        m.assert_called_once_with(ADDR, 11155111)

    def test_auditor_failure_is_502_never_200(self):
        with mock.patch.object(auditor, "screen", side_effect=auditor.AuditorError("rpc down")):
            status, body = server.handle(f"/screen?address={ADDR}")
        self.assertEqual((status, body), (502, {"error": "rpc down"}))

    @unittest.skipUnless(server.jsonschema and server.SCHEMA, "jsonschema or schema file missing")
    def test_schema_invalid_output_is_500(self):
        with mock.patch.object(auditor, "screen", return_value={"verdict": "SAFE"}):
            status, _ = server.handle(f"/screen?address={ADDR}")
        self.assertEqual(status, 500)


class AddressFromTextTests(unittest.TestCase):
    def test_plain_address_and_link(self):
        self.assertEqual(server.address_from_text(f"screen {ADDR} please"), ADDR)
        self.assertEqual(server.address_from_text(f"https://sepolia.etherscan.io/address/{ADDR}"), ADDR)

    def test_known_alias_name(self):
        import aliases
        self.assertEqual(server.address_from_text("check vault.eth"), aliases.resolve("vault.eth"))

    def test_nothing_found(self):
        self.assertIsNone(server.address_from_text("hello there"))
        self.assertIsNone(server.address_from_text("unknown-name.eth"))


if __name__ == "__main__":
    unittest.main()
