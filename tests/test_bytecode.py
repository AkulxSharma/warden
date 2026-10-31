"""Bytecode detector tests on synthetic bytecode (no network, no solc).

Run from sessions/warden:
    PATH="$PWD/.venv/bin:$PATH" python3 -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bytecode  # noqa: E402


def ids(findings):
    return {f["id"] for f in findings}


class BytecodeTests(unittest.TestCase):
    def test_eoa(self):
        out = bytecode.analyze_bytecode(b"")
        self.assertEqual(ids(out), {"eoa"})
        self.assertEqual(out[0]["severity"], "low")

    def test_eip7702_delegation(self):
        code = bytes.fromhex("ef0100" + "11" * 20)
        out = bytecode.analyze_bytecode(code)
        self.assertEqual(ids(out), {"eip7702-delegation"})
        self.assertEqual(out[0]["severity"], "high")
        self.assertIn("0x" + "11" * 20, out[0]["message"])

    def test_7702_needs_exact_length_and_prefix(self):
        self.assertIsNone(bytecode.delegation_target(bytes.fromhex("ef0100" + "11" * 19)))
        self.assertIsNone(bytecode.delegation_target(bytes.fromhex("ef0101" + "11" * 20)))

    def test_opcode_in_push_data_is_ignored(self):
        # PUSH1 0xff, STOP: the 0xff is data, not SELFDESTRUCT
        self.assertEqual(bytecode.analyze_bytecode(bytes([0x60, 0xFF, 0x00])), [])
        # PUSH32 whose data contains DELEGATECALL / ORIGIN bytes, then STOP
        self.assertEqual(bytecode.analyze_bytecode(bytes([0x7F]) + bytes([0xF4, 0x32] * 16) + b"\x00"), [])

    def test_real_opcodes_are_flagged(self):
        self.assertEqual(ids(bytecode.analyze_bytecode(bytes([0x00, 0xFF]))), {"selfdestruct-opcode"})
        self.assertEqual(ids(bytecode.analyze_bytecode(bytes([0x00, 0xF4]))), {"delegatecall-opcode"})
        self.assertEqual(ids(bytecode.analyze_bytecode(bytes([0x00, 0xF2]))), {"delegatecall-opcode"})
        self.assertEqual(ids(bytecode.analyze_bytecode(bytes([0x00, 0x32]))), {"origin-opcode"})

    def test_known_selectors(self):
        by_name = {sig: sel for sel, (sig, _) in bytecode.ADMIN_SELECTORS.items()}
        self.assertEqual(by_name["upgradeTo(address)"].hex(), "3659cfe6")
        self.assertEqual(by_name["mint(address,uint256)"].hex(), "40c10f19")
        self.assertEqual(by_name["transferOwnership(address)"].hex(), "f2fde38b")

    def test_admin_selector_severity(self):
        sel = lambda sig: next(s for s, (g, _) in bytecode.ADMIN_SELECTORS.items() if g == sig)
        power = bytes([0x63]) + sel("mint(address,uint256)") + b"\x00"
        own = bytes([0x63]) + sel("transferOwnership(address)") + b"\x00"
        p = bytecode.analyze_bytecode(power)
        o = bytecode.analyze_bytecode(own)
        self.assertEqual((p[0]["id"], p[0]["severity"]), ("admin-selectors", "medium"))
        self.assertIn("mint(address,uint256)", p[0]["message"])
        self.assertEqual((o[0]["id"], o[0]["severity"]), ("admin-selectors", "low"))

    def test_eip1967_slot_constant_and_flag(self):
        self.assertEqual(bytecode.PROXY_SLOTS["implementation"],
                         "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc")
        code = bytes([0x00])
        zero = "0x" + "00" * 32
        set_ = "0x" + "00" * 12 + "ab" * 20
        self.assertEqual(bytecode.analyze_bytecode(code, {"implementation": zero}), [])
        self.assertEqual(ids(bytecode.analyze_bytecode(code, {"implementation": set_})), {"eip1967-proxy"})

    def test_findings_match_contract_fields(self):
        for f in bytecode.analyze_bytecode(bytes([0x00, 0xFF, 0xF4, 0x32])):
            self.assertEqual(set(f), {"id", "severity", "message"})
            self.assertIn(f["severity"], {"high", "medium", "low"})


if __name__ == "__main__":
    unittest.main()
