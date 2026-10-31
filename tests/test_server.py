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


if __name__ == "__main__":
    unittest.main()
