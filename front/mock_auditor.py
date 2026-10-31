"""Mock Auditor (stand-in for workstream 1).

Same signature and output shape as the real Auditor:
    audit(address, chain_id=None, calldata=None, value=None) -> dict

Three demo addresses map to the LOW / MEDIUM / HIGH fixtures. Any other
address gets one of the three, picked by a stable hash so repeat scans agree.
"""
import copy
import hashlib
import json
from pathlib import Path

from .parse import SEPOLIA

DATA = Path(__file__).resolve().parent.parent / "fixtures" / "auditor-output"  # shared team fixtures
LEVELS = ("low", "medium", "high")
_FIXTURES = {name: json.loads((DATA / f"{name}.json").read_text()) for name in LEVELS}
DEMO_ADDRESSES = {fx["target"].lower(): name for name, fx in _FIXTURES.items()}


def audit(address, chain_id=None, calldata=None, value=None):
    level = DEMO_ADDRESSES.get(address.lower())
    if level is None:
        level = LEVELS[int(hashlib.sha256(address.lower().encode()).hexdigest(), 16) % 3]
    result = copy.deepcopy(_FIXTURES[level])
    result["target"] = address
    result["chainId"] = chain_id or SEPOLIA
    return result
