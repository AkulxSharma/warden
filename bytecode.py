"""Bytecode checks for addresses with no verified source. Pure functions, no network.

Findings use the Auditor contract shape: {"id", "severity", "message"}.
A clean result means nothing was flagged, never that the address is safe.
"""
from eth_utils import keccak

OP_ORIGIN = 0x32
OP_PUSH1 = 0x60
OP_PUSH4 = 0x63
OP_PUSH32 = 0x7F
OP_CALLCODE = 0xF2
OP_DELEGATECALL = 0xF4
OP_SELFDESTRUCT = 0xFF

DELEGATION_PREFIX = bytes.fromhex("ef0100")  # EIP-7702: prefix + 20-byte delegate = 23 bytes


def _eip1967_slot(label):
    return "0x" + (int.from_bytes(keccak(text=label), "big") - 1).to_bytes(32, "big").hex()


PROXY_SLOTS = {
    "implementation": _eip1967_slot("eip1967.proxy.implementation"),
    "admin": _eip1967_slot("eip1967.proxy.admin"),
    "beacon": _eip1967_slot("eip1967.proxy.beacon"),
}

# Owner-only functions. "power" = can change code, supply, or who may transact.
ADMIN_SIGNATURES = {
    "upgradeTo(address)": "power",
    "upgradeToAndCall(address,bytes)": "power",
    "mint(address,uint256)": "power",
    "pause()": "power",
    "unpause()": "power",
    "blacklist(address)": "power",
    "transferOwnership(address)": "ownership",
    "renounceOwnership()": "ownership",
}
ADMIN_SELECTORS = {keccak(text=sig)[:4]: (sig, kind) for sig, kind in ADMIN_SIGNATURES.items()}


def delegation_target(code):
    """Return the delegate address if code is an EIP-7702 delegation designator, else None."""
    if len(code) == 23 and code[:3] == DELEGATION_PREFIX:
        return "0x" + code[3:].hex()
    return None


def scan_opcodes(code):
    """Walk the code, skipping PUSH immediate data. Returns (opcodes seen, PUSH4 values seen)."""
    ops, push4 = set(), set()
    i = 0
    while i < len(code):
        op = code[i]
        if OP_PUSH1 <= op <= OP_PUSH32:
            size = op - OP_PUSH1 + 1
            if op == OP_PUSH4 and i + 5 <= len(code):
                push4.add(bytes(code[i + 1:i + 5]))
            i += 1 + size
        else:
            ops.add(op)
            i += 1
    return ops, push4


def analyze_bytecode(code, proxy_slots=None):
    """Return contract-shaped findings for runtime bytecode.

    code: bytes from eth_getCode. proxy_slots: optional {"implementation"|"admin"|"beacon": 32-byte
    storage value as bytes or hex string}; any non-zero value flags an EIP-1967 proxy.
    """
    if len(code) == 0:
        return [{"id": "eoa", "severity": "low",
                 "message": "address has no contract code (EOA); contract checks do not apply"}]

    target = delegation_target(code)
    if target:
        return [{"id": "eip7702-delegation", "severity": "high",
                 "message": f"address is an EOA delegated by EIP-7702 to {target}; "
                            "its behavior is set by that contract"}]

    findings = []
    ops, push4 = scan_opcodes(code)

    if OP_SELFDESTRUCT in ops:
        findings.append({"id": "selfdestruct-opcode", "severity": "high",
                         "message": "bytecode contains a SELFDESTRUCT opcode"})
    if OP_DELEGATECALL in ops or OP_CALLCODE in ops:
        findings.append({"id": "delegatecall-opcode", "severity": "medium",
                         "message": "bytecode contains DELEGATECALL or CALLCODE; "
                                    "external code can run with this contract's storage"})
    if OP_ORIGIN in ops:
        findings.append({"id": "origin-opcode", "severity": "medium",
                         "message": "bytecode reads tx.origin (phishing-prone auth)"})

    for name, value in (proxy_slots or {}).items():
        raw = bytes.fromhex(value[2:]) if isinstance(value, str) else bytes(value)
        if any(raw):
            findings.append({"id": "eip1967-proxy", "severity": "medium",
                             "message": f"EIP-1967 {name} slot is set; the logic behind this "
                                        "address can be changed by its admin"})
            break

    found = sorted((ADMIN_SELECTORS[s] for s in push4 if s in ADMIN_SELECTORS))
    if found:
        names = ", ".join(sig for sig, _ in found)
        severity = "medium" if any(kind == "power" for _, kind in found) else "low"
        findings.append({"id": "admin-selectors", "severity": severity,
                         "message": f"owner-only functions present: {names}"})

    return findings
