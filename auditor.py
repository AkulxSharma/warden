#!/usr/bin/env python3
"""Warden Auditor: Analysis Core. Emits the fixed contract from tasks/1-auditor.md.

Slice 1: verified-source path only, input is a local .sol file.
Not yet built: Etherscan fetch, bytecode path (7702 / 1967 / opcodes), anvil fork sim.

Output is a risk signal, not an audit. Never report "safe".
"""
import json
import sys
from pathlib import Path

import warden_scan

DEFAULT_CHAIN_ID = 11155111  # Sepolia. Testnet only until Akul says otherwise.
SEVERITY_LOWER = {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}

# Provisional scoring. Verdict = worst finding severity (same rule as warden_scan).
# riskScore = 50 per HIGH, 15 per MEDIUM, 5 per LOW, capped at 100. Tune later.
SCORE_WEIGHT = {"HIGH": 50, "MEDIUM": 15, "LOW": 5}


def score(findings):
    return min(100, sum(SCORE_WEIGHT[f.severity] for f in findings))


def analyze_source(path, chain_id=DEFAULT_CHAIN_ID, target=None, solc="solc"):
    """Run the static detectors on a Solidity file and return the Auditor contract dict."""
    findings = warden_scan.scan(str(path), solc=solc)
    # verdict from warden_scan returns CLEAN for zero findings; Warden contract has no CLEAN.
    verdict = warden_scan.verdict(findings)
    if verdict == "CLEAN":
        verdict = "LOW"
    return {
        "target": target or Path(path).name,
        "chainId": chain_id,
        "verdict": verdict,
        "riskScore": score(findings),
        "verified": True,
        "findings": [
            {
                "id": f.id,
                "severity": SEVERITY_LOWER[f.severity],
                "message": f"{f.message} (in {f.function}, line {f.line})",
            }
            for f in findings
        ],
    }


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    result = analyze_source(argv[0])
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
