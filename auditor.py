#!/usr/bin/env python3
"""Warden Auditor: Analysis Core. Emits the fixed contract in schema/auditor-output.schema.json.

    python3 auditor.py 0x<address> [chainId]     screen an address (needs network, ETHERSCAN_API_KEY)
    python3 auditor.py path/to/Contract.sol      scan local source

Output is a risk signal, not an audit. Never report "safe". Calldata and value are accepted by
screen() but unused until the fork simulation exists.
"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import bytecode
import chain
import etherscan
import warden_scan

DEFAULT_CHAIN_ID = 11155111  # Sepolia. Testnet only until Akul says otherwise.
ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

# Provisional scoring. Verdict = worst finding severity.
# riskScore = 50 per high, 15 per medium, 5 per low, capped at 100.
SCORE_WEIGHT = {"high": 50, "medium": 15, "low": 5}
SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1}

SOURCE_ERRORS = (RuntimeError, OSError, KeyError, ValueError)


class AuditorError(Exception):
    """The screen could not run. Callers must treat this as 'refuse', never as 'low risk'."""


def score(findings):
    return min(100, sum(SCORE_WEIGHT[f["severity"]] for f in findings))


def verdict_of(findings):
    if not findings:
        return "LOW"
    return max(findings, key=lambda f: SEVERITY_RANK[f["severity"]])["severity"].upper()


def build_result(target, chain_id, findings, verified):
    return {
        "target": target,
        "chainId": chain_id,
        "verdict": verdict_of(findings),
        "riskScore": score(findings),
        "verified": verified,
        "findings": findings,
    }


def _from_scan(found):
    return [{"id": f.id, "severity": f.severity.lower(),
             "message": f"{f.message} (in {f.function}, line {f.line})"} for f in found]


def analyze_source(path, chain_id=DEFAULT_CHAIN_ID, target=None, solc="solc"):
    """Run the static detectors on a Solidity file and return the Auditor contract dict."""
    findings = _from_scan(warden_scan.scan(str(path), solc=solc))
    return build_result(target or Path(path).name, chain_id, findings, True)


def _scan_source_text(text, solc):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "Contract.sol"
        path.write_text(text, encoding="utf-8")
        return _from_scan(warden_scan.scan(str(path), solc=solc))


def screen(address, chain_id=DEFAULT_CHAIN_ID, calldata=None, value=None, solc="solc", api_key=None):
    """Screen an address. Raises AuditorError if the check cannot run."""
    if not ADDRESS_RE.match(address or ""):
        raise AuditorError("invalid address")
    api_key = api_key or os.environ.get("ETHERSCAN_API_KEY")

    try:
        code = chain.get_code(chain_id, address)
        if len(code) == 0 or bytecode.delegation_target(code):
            return build_result(address, chain_id, bytecode.analyze_bytecode(code), False)
        slots = {name: chain.get_storage_at(chain_id, address, slot)
                 for name, slot in bytecode.PROXY_SLOTS.items()}
        src = etherscan.get_source(chain_id, address, api_key) if api_key else None
    except (chain.ChainError, etherscan.EtherscanError) as exc:
        raise AuditorError(str(exc)) from exc

    code_findings = bytecode.analyze_bytecode(code, slots)

    if src is None:
        extra = [{"id": "unverified-source", "severity": "medium",
                  "message": "source is not verified; bytecode checks only"}]
    else:
        reason = "verified source has multiple files" if src["kind"] == "multi" else None
        if src["kind"] == "single":
            try:
                found = _scan_source_text(src["source"], solc)
            except SOURCE_ERRORS:
                reason = "verified source could not be compiled here"
            else:
                # admin powers and upgradeability exist whether or not the source is verified
                kept = [f for f in code_findings if f["id"] in ("eip1967-proxy", "admin-selectors")]
                return build_result(address, chain_id, found + kept, True)
        extra = [{"id": "source-not-scanned", "severity": "medium",
                  "message": f"{reason}; bytecode checks only"}]

    return build_result(address, chain_id, code_findings + extra, False)


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    target = argv[0]
    if target.endswith(".sol"):
        result = analyze_source(target)
    else:
        chain_id = int(argv[1]) if len(argv) > 1 else DEFAULT_CHAIN_ID
        try:
            result = screen(target, chain_id)
        except AuditorError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
