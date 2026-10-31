"""Front-end tests: parser, mocks, pipeline. Run: python3 -m unittest discover tests"""
import os
import re
import tempfile
import unittest
from pathlib import Path

os.environ["WARDEN_AUDITOR_URL"] = ""  # keep a live URL in .env out of the tests

from front import mock_agent, mock_auditor, pipeline
from front import config
from front.imessage import decode_attributed_body, mask, wants_warden
from front.parse import SEPOLIA, parse

LOW, MED, HIGH = (f["target"] for f in mock_auditor._FIXTURES.values())
CONTRACT_KEYS = {"target", "chainId", "verdict", "riskScore", "verified", "findings"}


class ParseTest(unittest.TestCase):
    def test_bare_address(self):
        p = parse(f"check {HIGH} pls")
        self.assertEqual((p.kind, p.address, p.chain_id, p.is_link), ("scan", HIGH, None, False))

    def test_explorer_link_sets_chain(self):
        p = parse(f"https://sepolia.etherscan.io/address/{MED}")
        self.assertEqual((p.kind, p.chain_id, p.is_link), ("scan", SEPOLIA, True))
        self.assertEqual(parse(f"https://etherscan.io/address/{MED}").chain_id, 1)

    def test_chain_word(self):
        self.assertEqual(parse(f"{LOW} on base").chain_id, 8453)

    def test_not_addresses(self):
        self.assertEqual(parse("0x" + "a" * 64).kind, "tx_hash")
        self.assertEqual(parse("vitalik.eth").kind, "ens")
        self.assertEqual(parse("https://uniswap.org/swap").kind, "link_no_address")
        self.assertEqual(parse("hi").kind, "help")
        self.assertEqual(parse("what is tx.origin").kind, "text")
        self.assertEqual(parse("0x123").kind, "text")


class MockTest(unittest.TestCase):
    def test_auditor_shape(self):
        for addr in (LOW, MED, HIGH, "0x" + "ab" * 20):
            r = mock_auditor.audit(addr)
            self.assertEqual(set(r), CONTRACT_KEYS)
            self.assertEqual(r["target"], addr)
            self.assertIn(r["verdict"], {"LOW", "MEDIUM", "HIGH"})

    def test_reply_only_uses_present_findings_and_never_says_safe(self):
        all_ids = {f["id"] for fx in mock_auditor._FIXTURES.values() for f in fx["findings"]}
        for addr in (LOW, MED, HIGH):
            r = mock_auditor.audit(addr)
            text = mock_agent.reply(r)
            self.assertNotRegex(text, re.compile(r"\bsafe\b", re.I))
            self.assertIn("not a guarantee", text)
            self.assertIn(f"risk signal: {r['verdict']}", text)
            present = {f["message"] for f in r["findings"]}
            absent = {f["message"] for fx in mock_auditor._FIXTURES.values()
                      for f in fx["findings"]} - present
            for msg in absent:
                self.assertNotIn(msg, text)
            self.assertTrue(all_ids)

    def test_unverified_is_disclosed(self):
        self.assertIn("bytecode checks only", mock_agent.reply(mock_auditor.audit(HIGH)))

    def test_followup_does_not_invent(self):
        r = mock_auditor.audit(HIGH)
        self.assertIn("did not flag", mock_agent.followup(r, "is there reentrancy?"))
        self.assertIn("eip7702-delegation", mock_agent.followup(r, "what is the delegation thing"))


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = pipeline.EVENTS
        pipeline.EVENTS = Path(self.tmp.name) / "events.jsonl"
        pipeline._sessions.clear()

    def tearDown(self):
        pipeline.EVENTS = self.old
        self.tmp.cleanup()

    def test_scan_then_followup_then_log(self):
        out = pipeline.handle_message(HIGH, session="a")
        self.assertEqual((out["kind"], out["result"]["verdict"]), ("scan", "HIGH"))
        out = pipeline.handle_message("explain delegatecall", session="a")
        self.assertEqual(out["kind"], "followup")
        self.assertEqual(len(pipeline.read_events()), 2)

    def test_non_sepolia_blocked(self):
        out = pipeline.handle_message(f"{LOW} mainnet", session="b")
        self.assertEqual((out["kind"], out["result"]), ("blocked_chain", None))

    def test_no_session_asks_for_address(self):
        self.assertEqual(pipeline.handle_message("yo", session="c")["reply"], pipeline.ASK_ADDRESS)


class TransferFlowTest(unittest.TestCase):
    """The gate is code: HIGH or a failed check refuses; YES only after a passing check."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = pipeline.EVENTS
        pipeline.EVENTS = Path(self.tmp.name) / "events.jsonl"
        pipeline._sessions.clear()

    def tearDown(self):
        pipeline.EVENTS = self.old
        self.tmp.cleanup()

    def send(self, text, session="t", team=True):
        return pipeline.handle_message(text, session=session, can_transfer=team)

    def test_gate(self):
        a = "0x" + "4" * 40

        def scan(verdict="LOW", findings=(), target=a, chain=11155111):
            return {"target": target, "chainId": chain, "verdict": verdict, "riskScore": 5,
                    "verified": True, "findings": list(findings)}
        high = {"id": "selfdestruct-opcode", "severity": "high", "message": "m"}
        self.assertEqual(pipeline.gate(None, a), "refuse")
        self.assertEqual(pipeline.gate(scan("HIGH"), a), "refuse")
        self.assertEqual(pipeline.gate(scan("MEDIUM"), a), "confirm")
        self.assertEqual(pipeline.gate(scan("LOW"), a), "confirm")
        self.assertEqual(pipeline.gate(scan("LOW", [high]), a), "refuse")          # high finding, low verdict
        self.assertEqual(pipeline.gate(scan(target="0x" + "5" * 40), a), "refuse")  # wrong address
        self.assertEqual(pipeline.gate(scan(chain=1), a), "refuse")                 # wrong chain
        self.assertEqual(pipeline.gate({"verdict": "LOW"}, a), "refuse")            # not schema-valid

    def test_high_refused_and_yes_sends_nothing(self):
        self.assertEqual(self.send(f"send 0.01 to {HIGH}")["kind"], "refused")
        self.assertEqual(self.send("YES")["kind"], "yes_nothing")

    def test_medium_asks_then_yes_confirms(self):
        out = self.send(f"send 0.01 to {MED}")
        self.assertEqual(out["kind"], "confirm")
        self.assertIn("Reply YES", out["reply"])
        self.assertEqual(self.send("yes")["kind"], "demo_sent")
        self.assertEqual(self.send("yes")["kind"], "yes_nothing")

    def test_no_cancels(self):
        self.send(f"send 0.01 to {LOW}")
        self.assertEqual(self.send("no")["reply"], pipeline.CANCELLED)
        self.assertEqual(self.send("yes")["kind"], "yes_nothing")

    def test_auditor_failure_refuses(self):
        from unittest import mock
        with mock.patch.object(pipeline.services, "audit", side_effect=pipeline.services.AuditorError("down")):
            out = self.send(f"send 0.01 to {LOW}")
        self.assertEqual((out["kind"], out["reply"]), ("refused", pipeline.CHECK_FAILED))
        self.assertEqual(self.send("yes")["kind"], "yes_nothing")

    def test_strangers_and_web_never_get_a_pending_send(self):
        out = self.send(f"send 0.01 to {LOW}", session="s", team=False)
        self.assertEqual(out["kind"], "screened")
        self.assertEqual(self.send("yes", session="s", team=False)["kind"], "yes_nothing")

    def test_amount_cap_and_missing_amount(self):
        self.assertEqual(self.send(f"send 5 eth to {LOW}")["kind"], "blocked_amount")
        self.assertEqual(self.send(f"send to {LOW}")["kind"], "need_amount")

    def test_expired_pending(self):
        self.send(f"send 0.01 to {LOW}")
        pipeline._sessions["t"]["pending"]["ts"] -= pipeline.PENDING_TTL + 1
        self.assertEqual(self.send("yes")["kind"], "expired")


class IMessageHelpersTest(unittest.TestCase):
    def test_decode_attributed_body(self):
        text = "check 0xabc"
        blob = b"\x04\x0bstreamtyped\x81\xe8\x03\x84\x01@\x84\x84\x84\x12NSAttributedString\x00\x84\x84\x08NSObject\x00\x85\x92\x84\x84\x84\x08NSString\x01\x94\x84\x01+" \
               + bytes([len(text)]) + text.encode() + b"\x86\x84"
        self.assertEqual(decode_attributed_body(blob), text)

    def test_public_mode_skips_normal_texts(self):
        self.assertTrue(wants_warden(f"is {HIGH} legit?"))
        self.assertTrue(wants_warden("hey warden"))
        self.assertTrue(wants_warden(f"send 0.01 to {LOW}"))
        self.assertTrue(wants_warden("https://sepolia.etherscan.io/address/0x123"))
        self.assertFalse(wants_warden("hi"))
        self.assertFalse(wants_warden("dinner at 7?"))

    def test_load_env(self):
        with tempfile.TemporaryDirectory() as d:
            env = Path(d) / ".env"
            env.write_text("# comment\nWARDEN_TEST_A=+15550001111 # note\nWARDEN_TEST_B='x@y.com, +15552223333'\n")
            config.load_env(env)
            self.assertEqual(config.os.environ["WARDEN_TEST_A"], "+15550001111")
            self.assertEqual(config.handles("WARDEN_TEST_B"), ["x@y.com", "+15552223333"])

    def test_mask(self):
        self.assertEqual(mask("+15551234567"), "…4567")
        self.assertEqual(mask("drew@icloud.com"), "dr…@icloud.com")


if __name__ == "__main__":
    unittest.main()


class AliasParseTest(unittest.TestCase):
    def test_known_alias_parses_as_its_address_and_unknown_stays_ens(self):
        import aliases
        p = parse("send 0.01 to Akul.eth")
        self.assertEqual((p.kind, p.address), ("transfer", aliases.resolve("akul.eth")))
        self.assertEqual(parse("send 0.01 to eve.eth").kind, "ens")
