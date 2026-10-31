"""Auditor slice-1 tests: verified-source path against fixtures.

Run from sessions/warden with the venv on PATH so solc resolves:
    PATH="$PWD/.venv/bin:$PATH" python3 -m unittest discover -s tests -v
"""
import shutil
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import auditor  # noqa: E402

FIX = ROOT / "fixtures"
REQUIRED_KEYS = {"target", "chainId", "verdict", "riskScore", "verified", "findings"}


@unittest.skipUnless(shutil.which("solc"), "solc not on PATH (use .venv/bin)")
class SourcePathTests(unittest.TestCase):
    def test_vulnerable_is_high_with_expected_detectors(self):
        out = auditor.analyze_source(FIX / "Vulnerable.sol")
        self.assertEqual(set(out.keys()), REQUIRED_KEYS)
        self.assertEqual(out["verdict"], "HIGH")
        self.assertTrue(out["verified"])
        ids = {f["id"] for f in out["findings"]}
        self.assertTrue({"reentrancy-state-after-call", "unprotected-state-write",
                         "arbitrary-send", "tx-origin"} <= ids, ids)
        self.assertGreater(out["riskScore"], 0)
        self.assertLessEqual(out["riskScore"], 100)

    def test_safe_is_low_with_no_findings(self):
        out = auditor.analyze_source(FIX / "Safe.sol")
        self.assertEqual(set(out.keys()), REQUIRED_KEYS)
        self.assertEqual(out["verdict"], "LOW")
        self.assertEqual(out["findings"], [])
        self.assertEqual(out["riskScore"], 0)

    def test_findings_have_contract_fields_and_lowercase_severity(self):
        out = auditor.analyze_source(FIX / "Vulnerable.sol")
        for f in out["findings"]:
            self.assertEqual(set(f.keys()), {"id", "severity", "message"})
            self.assertIn(f["severity"], {"high", "medium", "low"})

    def test_chain_id_defaults_to_sepolia(self):
        self.assertEqual(auditor.analyze_source(FIX / "Safe.sol")["chainId"], 11155111)


if __name__ == "__main__":
    unittest.main()
