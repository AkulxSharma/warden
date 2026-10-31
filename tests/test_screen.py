"""screen() tests with chain and Etherscan mocked. No network. Source cases need solc on PATH.

Run from sessions/warden:
    PATH="$PWD/.venv/bin:$PATH" python3 -m unittest discover -s tests -v
"""
import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import auditor  # noqa: E402
import bytecode  # noqa: E402
import chain  # noqa: E402
import etherscan  # noqa: E402

try:
    import jsonschema
except ImportError:  # schema check is skipped, everything else still runs
    jsonschema = None

ADDR = "0x" + "11" * 20
ZERO32 = b"\x00" * 32
SCHEMA = json.loads((ROOT / "schema" / "auditor-output.schema.json").read_text())
HAS_SOLC = bool(shutil.which("solc"))


def ids(out):
    return {f["id"] for f in out["findings"]}


class ScreenTests(unittest.TestCase):
    def run_screen(self, code, source=None, slots=None, address=ADDR, api_key="k"):
        slots = slots or {}
        storage = lambda cid, addr, slot: slots.get(slot, ZERO32)
        with mock.patch.object(chain, "get_code", return_value=code), \
                mock.patch.object(chain, "get_storage_at", side_effect=storage), \
                mock.patch.object(etherscan, "get_source", return_value=source):
            out = auditor.screen(address, api_key=api_key)
        if jsonschema:
            jsonschema.validate(out, SCHEMA)
        return out

    def test_invalid_address_raises(self):
        with self.assertRaises(auditor.AuditorError):
            auditor.screen("not-an-address")

    def test_eoa_is_low_unverified(self):
        out = self.run_screen(b"")
        self.assertEqual((out["verdict"], out["verified"], ids(out)), ("LOW", False, {"eoa"}))

    def test_7702_delegation_is_high(self):
        out = self.run_screen(bytes.fromhex("ef0100" + "22" * 20))
        self.assertEqual((out["verdict"], ids(out)), ("HIGH", {"eip7702-delegation"}))

    def test_unverified_contract_uses_bytecode_path(self):
        out = self.run_screen(bytes([0x00, 0xFF]), source=None)
        self.assertEqual(out["verdict"], "HIGH")
        self.assertFalse(out["verified"])
        self.assertEqual(ids(out), {"selfdestruct-opcode", "unverified-source"})

    def test_no_api_key_falls_back_to_bytecode_path(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            out = self.run_screen(bytes([0x00]), source=None, api_key=None)
        self.assertEqual((out["verdict"], out["verified"]), ("MEDIUM", False))
        self.assertEqual(ids(out), {"unverified-source"})

    @unittest.skipUnless(HAS_SOLC, "solc not on PATH (use .venv/bin)")
    def test_verified_vulnerable_source_is_high(self):
        src = {"kind": "single", "source": (ROOT / "fixtures" / "Vulnerable.sol").read_text()}
        out = self.run_screen(bytes([0x00]), source=src)
        self.assertEqual((out["verdict"], out["verified"]), ("HIGH", True))
        self.assertIn("reentrancy-state-after-call", ids(out))

    @unittest.skipUnless(HAS_SOLC, "solc not on PATH (use .venv/bin)")
    def test_verified_safe_source_is_low(self):
        src = {"kind": "single", "source": (ROOT / "fixtures" / "Safe.sol").read_text()}
        out = self.run_screen(bytes([0x00]), source=src)
        self.assertEqual((out["verdict"], out["verified"], out["findings"]), ("LOW", True, []))

    @unittest.skipUnless(HAS_SOLC, "solc not on PATH (use .venv/bin)")
    def test_verified_source_still_reports_proxy(self):
        src = {"kind": "single", "source": (ROOT / "fixtures" / "Safe.sol").read_text()}
        slot = bytecode.PROXY_SLOTS["implementation"]
        out = self.run_screen(bytes([0x00]), source=src, slots={slot: b"\x00" * 12 + b"\xab" * 20})
        self.assertEqual(ids(out), {"eip1967-proxy"})
        self.assertTrue(out["verified"])

    def test_uncompilable_source_falls_back_honestly(self):
        src = {"kind": "single", "source": "this is not solidity"}
        out = self.run_screen(bytes([0x00]), source=src)
        self.assertFalse(out["verified"])
        self.assertEqual(ids(out), {"source-not-scanned"})

    def test_multi_file_source_falls_back_honestly(self):
        out = self.run_screen(bytes([0x00]), source={"kind": "multi", "source": {}})
        self.assertFalse(out["verified"])
        self.assertIn("source-not-scanned", ids(out))

    def test_chain_failure_raises_not_low(self):
        with mock.patch.object(chain, "get_code", side_effect=chain.ChainError("down")):
            with self.assertRaises(auditor.AuditorError):
                auditor.screen(ADDR, api_key="k")

    def test_etherscan_failure_raises_not_low(self):
        with mock.patch.object(chain, "get_code", return_value=bytes([0x00])), \
                mock.patch.object(chain, "get_storage_at", return_value=ZERO32), \
                mock.patch.object(etherscan, "get_source", side_effect=etherscan.EtherscanError("rate")):
            with self.assertRaises(auditor.AuditorError):
                auditor.screen(ADDR, api_key="k")


class ClassifyTests(unittest.TestCase):
    def test_single_file(self):
        self.assertEqual(etherscan.classify("contract A {}")[0], "single")

    def test_standard_json_double_braces(self):
        kind, parsed = etherscan.classify('{{"language":"Solidity","sources":{}}}')
        self.assertEqual((kind, parsed["language"]), ("multi", "Solidity"))

    def test_plain_json_sources(self):
        kind, _ = etherscan.classify('{"A.sol":{"content":"x"}}')
        self.assertEqual(kind, "multi")


if __name__ == "__main__":
    unittest.main()
