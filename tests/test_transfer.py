"""Transfer flow tests. Offline: fake Auditor, fake sender, fake wording, injected clock.

Run from the repo root with the venv:
    .venv/bin/python -m unittest discover -s tests -v
"""
import copy
import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import transfer  # noqa: E402
import wallet  # noqa: E402

try:
    import jsonschema
except ImportError:
    jsonschema = None

try:
    import eth_utils
except ImportError:
    eth_utils = None

A_LOW = "0x1111111111111111111111111111111111111111"
A_MED = "0x2222222222222222222222222222222222222222"
A_HIGH = "0x3333333333333333333333333333333333333333"
CHECKSUMMED = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"  # EIP-55 reference vector
ALICE = "+1 (415) 555-0100"
BOB = "bob@example.com"
TX = "0x" + "ab" * 32
HIGH_FINDING = {"id": "arbitrary-send", "severity": "high", "message": "sends ETH anywhere"}


def scan_for(address, verdict="LOW", findings=(), verified=True, score=0):
    return {"target": address, "chainId": 11155111, "verdict": verdict, "riskScore": score,
            "verified": verified, "findings": [dict(f) for f in findings]}


class Rig:
    """A Warden wired to fakes that record what happened."""

    def __init__(self, auditor=None, allowed=(ALICE, BOB), demo=False, send_error=None, explain=None):
        self.audit_calls, self.sent, self.now = [], [], 1000.0
        self.auditor_fn = auditor or (lambda address, chain: scan_for(address))
        self.send_error = send_error
        self.w = transfer.Warden(
            allowed, self._audit, self._send, clock=lambda: self.now, demo=demo,
            explain=explain or (lambda scan, note="": f"EXPLAIN {scan['verdict']}" + (f" | {note}" if note else "")),
            answer=lambda scan, question, history=(): f"ANSWER {question} h={len(history)}")

    def _audit(self, address, chain):
        self.audit_calls.append((address, chain))
        return self.auditor_fn(address, chain)

    def _send(self, to, wei):
        if self.send_error:
            raise self.send_error
        self.sent.append((to, wei))
        return TX

    def say(self, text, who=ALICE):
        return self.w.handle(who, text)


class ParseTests(unittest.TestCase):
    def test_transfers(self):
        for text, amount in ((f"send 0.01 to {A_LOW}", "0.01"), (f"Send 0.01 ETH to {A_LOW}", "0.01"),
                             (f"please send .5 to {A_LOW}", "0.5"), (f"transfer 1 to {A_LOW}.", "1"),
                             (f"pay {A_LOW} 0.0100", "0.01"), (f"send 0.01. to {A_LOW}", "0.01"),
                             (f"send 0.000000000000000001 sepolia eth to {A_LOW}", "0.000000000000000001")):
            intent = transfer.parse_intent(text)
            self.assertEqual(intent["kind"], "transfer", text)
            self.assertEqual(intent["address"], A_LOW)
            self.assertEqual(format(intent["amount"], "f"), amount, text)

    def test_unsafe_or_unclear_transfers_are_rejected(self):
        for text in (f"send 100 usdc to {A_LOW}", f"send $5 to {A_LOW}", f"send 1 btc to {A_LOW}",
                     f"send 5 wei to {A_LOW}", f"send -1 to {A_LOW}", f"send to {A_LOW}", f"send 0 to {A_LOW}",
                     f"send 0.0000000000000000001 to {A_LOW}", f"send 0,01 to {A_LOW}", f"send 1e3 to {A_LOW}",
                     f"send 5 and 6 to {A_LOW}", f"send 0.01 to {A_LOW} and {A_MED}",
                     f"send 0.01 mainnet {A_LOW}", f"send 0.01 on base to {A_LOW}"):
            self.assertEqual(transfer.parse_intent(text)["kind"], "bad", text)

    def test_screen_question_help(self):
        self.assertEqual(transfer.parse_intent(A_LOW)["kind"], "screen")
        self.assertEqual(transfer.parse_intent(f"is {A_LOW} ok?")["kind"], "screen")
        self.assertEqual(transfer.parse_intent("what does tx.origin mean?")["kind"], "question")
        self.assertEqual(transfer.parse_intent("   ")["kind"], "help")

    def test_a_transaction_hash_is_not_an_address(self):
        self.assertEqual(transfer.parse_intent("0x" + "ab" * 32)["kind"], "question")
        self.assertEqual(transfer.parse_intent("0x" + "a" * 41)["kind"], "question")

    def test_yes_and_no_are_strict(self):
        for text in ("YES", "yes", " Yes! ", "yes."):
            self.assertEqual(transfer.parse_intent(text)["kind"], "yes", text)
        for text in ("yes please", "yes send", "y", "ok", "yep", "sure", "yes 0.5"):
            self.assertNotEqual(transfer.parse_intent(text)["kind"], "yes", text)
        for text in ("no", "NO", "cancel", "stop."):
            self.assertEqual(transfer.parse_intent(text)["kind"], "no", text)


def mutations(good):
    """(label, doc) variants of a valid scan, each broken in one way. Floats are left out on purpose."""
    def with_(**over):
        doc = copy.deepcopy(good)
        doc.update(over)
        return doc

    def finding(**over):
        doc = copy.deepcopy(good)
        doc["findings"] = [dict({"id": "x", "severity": "high", "message": "m"}, **over)]
        return doc

    extra = copy.deepcopy(good)
    extra["extra"] = 1
    missing = copy.deepcopy(good)
    del missing["verified"]
    no_message = copy.deepcopy(good)
    no_message["findings"] = [{"id": "x", "severity": "high"}]
    extra_finding_key = copy.deepcopy(good)
    extra_finding_key["findings"] = [{"id": "x", "severity": "high", "message": "m", "more": 1}]
    return [
        ("extra key", extra), ("missing key", missing), ("no message", no_message),
        ("extra finding key", extra_finding_key),
        ("target short", with_(target="0x1234")), ("target no 0x", with_(target="1" * 42)),
        ("target 41 hex", with_(target="0x" + "1" * 41)), ("target newline", with_(target=A_LOW + "\n")),
        ("target name", with_(target="Vulnerable.sol")), ("target int", with_(target=5)),
        ("chain 0", with_(chainId=0)), ("chain str", with_(chainId="1")), ("chain bool", with_(chainId=True)),
        ("verdict CLEAN", with_(verdict="CLEAN")), ("verdict SAFE", with_(verdict="SAFE")),
        ("verdict lower", with_(verdict="low")), ("verdict None", with_(verdict=None)),
        ("score -1", with_(riskScore=-1)), ("score 101", with_(riskScore=101)),
        ("score str", with_(riskScore="5")), ("score bool", with_(riskScore=True)),
        ("verified str", with_(verified="true")), ("verified 1", with_(verified=1)),
        ("findings None", with_(findings=None)), ("findings dict", with_(findings={})),
        ("finding severity", finding(severity="critical")), ("finding severity upper", finding(severity="HIGH")),
        ("finding message int", finding(message=5)), ("finding id int", finding(id=5)),
        ("finding not dict", with_(findings=["x"])),
    ]


class GateTests(unittest.TestCase):
    def fixtures(self):
        for path in sorted((ROOT / "fixtures").glob("**/*.json")):
            yield path.name, json.loads(path.read_text(encoding="utf-8"))

    def test_real_fixtures_pass(self):
        seen = 0
        for name, doc in self.fixtures():
            if name.startswith("agent_") or doc.get("verdict"):
                self.assertTrue(transfer.check_scan(doc), name)
                seen += 1
        self.assertGreaterEqual(seen, 7)

    def test_broken_scans_fail(self):
        good = scan_for(A_LOW, "HIGH", [HIGH_FINDING], score=50)
        self.assertTrue(transfer.check_scan(good))
        for label, doc in mutations(good):
            self.assertFalse(transfer.check_scan(doc), label)
        for junk in (None, [], "", "{}", 5, {}):
            self.assertFalse(transfer.check_scan(junk), junk)

    @unittest.skipUnless(jsonschema, "jsonschema not installed")
    def test_same_answer_as_the_json_schema(self):
        schema = json.loads((ROOT / "schema" / "auditor-output.schema.json").read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        good = scan_for(A_LOW, "HIGH", [HIGH_FINDING], score=50)
        for label, doc in [("good", good)] + mutations(good):
            if label == "target newline":
                # Python's jsonschema lets "$" match before a trailing newline; the schema's own regex
                # dialect (and check_scan) do not. Being stricter here is the safe direction.
                self.assertFalse(transfer.check_scan(doc))
                continue
            self.assertEqual(transfer.check_scan(doc), validator.is_valid(doc), label)

    def test_gate_decisions(self):
        medium = {"id": "tx-origin", "severity": "medium", "message": "m"}
        low = {"id": "eoa", "severity": "low", "message": "m"}
        self.assertEqual(transfer.gate(scan_for(A_LOW)), "confirm")
        self.assertEqual(transfer.gate(scan_for(A_LOW, "LOW", [low])), "confirm")
        self.assertEqual(transfer.gate(scan_for(A_LOW, "MEDIUM", [medium])), "confirm")
        self.assertEqual(transfer.gate(scan_for(A_LOW, "HIGH", [HIGH_FINDING])), "refuse")
        self.assertEqual(transfer.gate(scan_for(A_LOW, "HIGH")), "refuse")                       # verdict alone
        self.assertEqual(transfer.gate(scan_for(A_LOW, "LOW", [HIGH_FINDING])), "refuse")        # finding alone
        self.assertEqual(transfer.gate(scan_for(A_LOW, "MEDIUM", [HIGH_FINDING])), "refuse")


class FlowTests(unittest.TestCase):
    def test_strangers_are_ignored_silently(self):
        rig = Rig()
        for text in (f"send 0.01 to {A_LOW}", "YES", A_LOW, "hello"):
            self.assertIsNone(rig.say(text, who="+19998887777"))
        self.assertEqual((rig.audit_calls, rig.sent), ([], []))

    def test_phone_numbers_match_by_digits(self):
        rig = Rig(allowed=["+14155550100"])
        self.assertIsNotNone(rig.say("hi", who="+1 415-555-0100"))
        self.assertIsNone(rig.say("hi", who="+14155550101"))
        rig = Rig(allowed=["Bob@Example.com"])
        self.assertIsNotNone(rig.say("hi", who="bob@example.COM"))

    def test_bridge_prefixes_are_ignored_when_matching(self):
        rig = Rig(allowed=["+14155550100", "bob@example.com"])
        for sender in ("tel:+14155550100", "iMessage;-;+14155550100", "SMS;-;+1 (415) 555-0100",
                       "any;+;+14155550100", "mailto:Bob@Example.com", "iMessage;-;bob@example.com"):
            self.assertIsNotNone(rig.say("hi", who=sender), sender)
        for sender in ("tel:+14155550101", "iMessage;-;eve@example.com", ";", ""):
            self.assertIsNone(rig.say("hi", who=sender), sender)

    def test_an_ignored_sender_is_logged_once_so_it_can_be_allowlisted(self):
        rig = Rig()
        with self.assertLogs("warden.transfer", "WARNING") as logs:
            rig.say("hi", who="+19998887777")
            rig.say("hi again", who="+19998887777")
            rig.say("hi", who="eve@example.com")
        self.assertEqual(len(logs.records), 2)
        self.assertIn("+19998887777", logs.output[0])
        self.assertNotIn("hi", logs.records[0].getMessage().replace("ignored", "").replace("allowlist", ""))

    def test_low_asks_then_sends_once(self):
        rig = Rig()
        ask = rig.say(f"send 0.01 to {A_LOW}")
        self.assertIn("Reply YES", ask)
        self.assertEqual(rig.sent, [])
        self.assertEqual(rig.audit_calls, [(A_LOW, 11155111)])
        done = rig.say("YES")
        self.assertEqual(rig.sent, [(A_LOW, 10 ** 16)])
        self.assertIn("Sent 0.01 ETH", done)
        self.assertIn(f"https://sepolia.etherscan.io/tx/{TX}", done)
        self.assertIn("Nothing is waiting", rig.say("YES"))
        self.assertEqual(len(rig.sent), 1)

    def test_medium_also_needs_a_yes(self):
        rig = Rig(auditor=lambda a, c: scan_for(a, "MEDIUM", [{"id": "tx-origin", "severity": "medium", "message": "m"}]))
        self.assertIn("Reply YES", rig.say(f"send 0.005 to {A_MED}"))
        self.assertEqual(rig.sent, [])
        rig.say("yes")
        self.assertEqual(rig.sent, [(A_MED, 5 * 10 ** 15)])

    def test_high_refuses_and_a_later_yes_sends_nothing(self):
        for scan in (scan_for(A_HIGH, "HIGH", [HIGH_FINDING], score=50),
                     scan_for(A_HIGH, "LOW", [HIGH_FINDING])):       # inconsistent Auditor
            rig = Rig(auditor=lambda a, c, s=scan: dict(s, target=a))
            reply = rig.say(f"send 0.01 to {A_HIGH}")
            self.assertIn("Not sent", reply)
            self.assertNotIn("Reply YES", reply)
            self.assertIn("Nothing is waiting", rig.say("YES"))
            self.assertEqual(rig.sent, [])

    def test_a_failed_check_refuses(self):
        def boom(address, chain):
            raise TimeoutError("slow")

        for auditor in (boom, lambda a, c: None, lambda a, c: {}, lambda a, c: "oops", lambda a, c: [],
                        lambda a, c: scan_for(a, "LOW", verified="yes"),
                        lambda a, c: dict(scan_for(a), extra=1),
                        lambda a, c: scan_for(A_MED),                       # a scan of another address
                        lambda a, c: dict(scan_for(a), chainId=1),          # another chain
                        transfer.no_auditor):
            rig = Rig(auditor=auditor)
            reply = rig.say(f"send 0.01 to {A_LOW}")
            self.assertIn("did not send anything", reply)
            self.assertIn("Nothing is waiting", rig.say("YES"))
            self.assertEqual(rig.sent, [])

    def test_cap_and_early_refusals_skip_the_auditor(self):
        rig = Rig()
        self.assertIn("limit of 0.01 ETH", rig.say(f"send 0.011 to {A_LOW}"))
        self.assertIn("zero address", rig.say("send 0.01 to 0x" + "0" * 40))
        self.assertEqual(rig.audit_calls, [])
        self.assertIn("Reply YES", rig.say(f"send 0.01 to {A_LOW}"))
        with mock.patch.dict("os.environ", {"WARDEN_MAX_ETH": "0.5"}):
            self.assertIn("Reply YES", rig.say(f"send 0.5 to {A_LOW}"))
            self.assertIn("limit of 0.5 ETH", rig.say(f"send 0.51 to {A_LOW}"))

    @unittest.skipUnless(eth_utils, "eth_utils not installed")
    def test_bad_checksum_is_refused_before_the_check(self):
        rig = Rig()
        self.assertIn("checksum", rig.say(f"send 0.01 to {CHECKSUMMED.replace('5aAe', '5aae')}"))
        self.assertEqual(rig.audit_calls, [])
        for ok in (CHECKSUMMED, CHECKSUMMED.lower(), "0x" + CHECKSUMMED[2:].upper()):
            self.assertIn("Reply YES", rig.say(f"send 0.01 to {ok}"))

    def test_screen_only_never_sends(self):
        rig = Rig()
        self.assertEqual(rig.say(A_LOW), "EXPLAIN LOW")
        self.assertIn("Nothing is waiting", rig.say("YES"))
        self.assertEqual(rig.sent, [])

    def test_a_new_address_replaces_or_clears_the_pending_request(self):
        rig = Rig(auditor=lambda a, c: scan_for(a, "HIGH", [HIGH_FINDING]) if a == A_HIGH else scan_for(a))
        rig.say(f"send 0.01 to {A_LOW}")
        rig.say(f"send 0.005 to {A_MED}")
        rig.say("YES")
        self.assertEqual(rig.sent, [(A_MED, 5 * 10 ** 15)])                        # only the newest
        rig.say(f"send 0.01 to {A_LOW}")
        rig.say(f"send 0.01 to {A_HIGH}")                                          # refused
        self.assertIn("Nothing is waiting", rig.say("YES"))
        rig.say(f"send 0.01 to {A_LOW}")
        rig.say(A_MED)                                                             # screen only
        self.assertIn("Nothing is waiting", rig.say("YES"))
        self.assertEqual(len(rig.sent), 1)

    def test_a_refused_or_unclear_request_also_clears_the_pending_one(self):
        for text in (f"send 0.02 to {A_MED}",                 # over the cap
                     f"send 100 usdc to {A_MED}",              # unclear
                     f"send 0.01 to 0x{'0' * 40}",             # zero address
                     f"send 0.01 to {A_MED} and {A_HIGH}"):    # two addresses
            rig = Rig()
            rig.say(f"send 0.01 to {A_LOW}")
            rig.say(text)
            self.assertIn("Nothing is waiting", rig.say("YES"), text)
            self.assertEqual(rig.sent, [], text)

    def test_yes_expires(self):
        rig = Rig()
        rig.say(f"send 0.01 to {A_LOW}")
        rig.now += transfer.PENDING_TTL + 1
        self.assertIn("expired", rig.say("YES"))
        self.assertEqual(rig.sent, [])
        rig.say(f"send 0.01 to {A_LOW}")
        rig.now += transfer.PENDING_TTL
        rig.say("YES")
        self.assertEqual(len(rig.sent), 1)

    def test_senders_are_isolated(self):
        rig = Rig()
        rig.say(f"send 0.01 to {A_LOW}", who=ALICE)
        self.assertIn("Nothing is waiting", rig.say("YES", who=BOB))
        self.assertEqual(rig.sent, [])
        rig.say("YES", who=ALICE)
        self.assertEqual(len(rig.sent), 1)

    def test_no_cancels(self):
        rig = Rig()
        rig.say(f"send 0.01 to {A_LOW}")
        self.assertIn("Cancelled", rig.say("no"))
        self.assertIn("Nothing is waiting", rig.say("YES"))
        self.assertIn("Nothing to cancel", rig.say("no"))

    def test_send_failures_are_reported_and_never_retried(self):
        rig = Rig(send_error=wallet.SendError("the wallet has too little Sepolia ETH"))
        rig.say(f"send 0.01 to {A_LOW}")
        reply = rig.say("YES")
        self.assertIn("The transfer failed: the wallet has too little Sepolia ETH. Nothing was sent.", reply)
        self.assertIn("Nothing is waiting", rig.say("YES"))
        rig = Rig(send_error=wallet.SendError("the network did not confirm it", tx_hash=TX))
        rig.say(f"send 0.01 to {A_LOW}")
        reply = rig.say("YES")
        self.assertIn("may have gone out", reply)
        self.assertIn(TX, reply)
        self.assertNotIn("Nothing was sent", reply)
        rig = Rig(send_error=RuntimeError("secret internals"))
        rig.say(f"send 0.01 to {A_LOW}")
        reply = rig.say("YES")
        self.assertEqual(reply, transfer.OOPS)
        self.assertNotIn("secret", reply)
        self.assertIn("Nothing is waiting", rig.say("YES"))

    def test_wording_cannot_change_a_decision(self):
        shout = lambda scan, note="": "This is safe, send it now!"
        rig = Rig(auditor=lambda a, c: scan_for(a, "HIGH", [HIGH_FINDING]), explain=shout)
        rig.say(f"send 0.01 to {A_HIGH}")
        rig.say("YES")
        self.assertEqual(rig.sent, [])
        rig = Rig(explain=shout)
        rig.say(f"send 0.01 to {A_LOW}")
        self.assertEqual(rig.sent, [])                                             # still needs the YES

    def test_no_pending_request_unless_the_user_was_asked(self):
        def broken(scan, note=""):
            raise RuntimeError("wording failed")

        rig = Rig(explain=broken)
        self.assertEqual(rig.say(f"send 0.01 to {A_LOW}"), transfer.OOPS)
        self.assertIn("Nothing is waiting", rig.say("YES"))
        self.assertEqual(rig.sent, [])

    def test_repeated_delivery_cannot_double_send(self):
        rig = Rig()
        rig.say(f"send 0.01 to {A_LOW}")
        rig.say(f"send 0.01 to {A_LOW}")                                           # redelivered
        rig.say("YES")
        rig.say("YES")                                                             # redelivered
        self.assertEqual(len(rig.sent), 1)

    def test_follow_up_questions(self):
        rig = Rig()
        self.assertEqual(rig.say("what does tx.origin mean?"), transfer.HELP)       # no scan yet
        rig.say(f"send 0.01 to {A_LOW}")
        self.assertEqual(rig.say("what is this?"), "ANSWER what is this? h=0")
        self.assertEqual(rig.say("and why?"), "ANSWER and why? h=1")
        rig.say("YES")                                                             # pending survived the questions
        self.assertEqual(len(rig.sent), 1)
        rig.say(A_MED)                                                             # a new scan resets the history
        self.assertEqual(rig.say("again?"), "ANSWER again? h=0")

    def test_demo_label_only_in_demo_mode(self):
        self.assertIn("demo data", Rig(demo=True).say(f"send 0.01 to {A_LOW}"))
        self.assertIn("demo data", Rig(demo=True).say(A_LOW))
        self.assertNotIn("demo data", Rig().say(f"send 0.01 to {A_LOW}"))

    def test_handle_never_raises(self):
        def explode(address, chain):
            raise KeyboardInterrupt if False else ValueError("x")

        rig = Rig(auditor=explode)
        self.assertIn("could", rig.say(A_LOW))
        for weird in (None, 5, "\x00", "😀" * 500, "send " * 5000):
            rig.w.handle(ALICE, weird)


class AuditorClientTests(unittest.TestCase):
    def serve(self, handler):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}"

    def test_http_auditor(self):
        seen = {}

        class Ok(BaseHTTPRequestHandler):
            def do_GET(self):
                seen["path"] = self.path
                body = json.dumps(scan_for(A_LOW)).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        call = transfer.http_auditor(self.serve(Ok))
        self.assertEqual(call(A_LOW, 11155111)["verdict"], "LOW")
        self.assertEqual(seen["path"], f"/screen?address={A_LOW}&chainId=11155111")

    def test_auditor_health_true_on_200(self):
        class Healthy(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args):
                pass

        self.assertTrue(transfer.auditor_health(self.serve(Healthy)))

    def test_auditor_health_false_on_error_status(self):
        class Unhealthy(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(500)
                self.end_headers()

            def log_message(self, *args):
                pass

        self.assertFalse(transfer.auditor_health(self.serve(Unhealthy)))

    def test_auditor_health_false_on_unreachable(self):
        self.assertFalse(transfer.auditor_health("http://127.0.0.1:1", timeout=1))

    def test_auditor_health_false_on_timeout(self):
        class Hang(BaseHTTPRequestHandler):
            def do_GET(self):
                threading.Event().wait(2)

            def log_message(self, *args):
                pass

        self.assertFalse(transfer.auditor_health(self.serve(Hang), timeout=0.2))

    def test_http_failures_raise_and_the_flow_refuses(self):
        class Broken(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(500)
                self.end_headers()

            def log_message(self, *args):
                pass

        class Garbage(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", "4")
                self.end_headers()
                self.wfile.write(b"nope")

            def log_message(self, *args):
                pass

        class Hang(BaseHTTPRequestHandler):
            def do_GET(self):
                threading.Event().wait(2)

            def log_message(self, *args):
                pass

        for handler, timeout in ((Broken, 5), (Garbage, 5), (Hang, 0.3)):
            call = transfer.http_auditor(self.serve(handler), timeout=timeout)
            with self.assertRaises(Exception):
                call(A_LOW, 11155111)
            rig = Rig(auditor=call)
            self.assertIn("did not send anything", rig.say(f"send 0.01 to {A_LOW}"))
            self.assertEqual(rig.sent, [])

    def test_bad_base_urls_are_rejected(self):
        for url in ("file:///etc/passwd", "ftp://x", "localhost:8000", ""):
            with self.assertRaises(ValueError):
                transfer.http_auditor(url)

    def test_fixture_auditor(self):
        call = transfer.fixture_auditor()
        for address, verdict in ((A_LOW, "LOW"), (A_MED, "MEDIUM"), (A_HIGH, "HIGH")):
            scan = call(address, 11155111)
            self.assertEqual((scan["verdict"], scan["target"]), (verdict, address))
            self.assertTrue(transfer.check_scan(scan))
        for other in ("0x9999999999999999999999999999999999999999", "0x1" + "a" * 39, "0x2" + "b" * 39,
                      "0x3" + "0" * 39, "0x" + "1" * 39 + "2"):         # look-alikes of the demo addresses
            with self.assertRaises(transfer.AuditorError, msg=other):
                call(other, 11155111)
            rig = Rig(auditor=call)
            self.assertIn("did not send anything", rig.say(f"send 0.01 to {other}"))
            self.assertEqual(rig.sent, [])

    def test_default_warden_fails_closed(self):
        env = {"WARDEN_ALLOWED_SENDERS": "a@x.com, +1 415 555 0100,", "WARDEN_AUDITOR_URL": "",
               "WARDEN_USE_FIXTURES": ""}
        with mock.patch.object(wallet, "load_env"), mock.patch.dict("os.environ", env):
            warden = transfer.default_warden()
            self.assertIs(warden.auditor, transfer.no_auditor)
            self.assertFalse(warden.demo)
            self.assertEqual(warden.allowed, {"a@x.com", "+14155550100"})
        with mock.patch.object(wallet, "load_env"), mock.patch.dict("os.environ", dict(env, WARDEN_USE_FIXTURES="1")):
            self.assertTrue(transfer.default_warden().demo)
        with mock.patch.object(wallet, "load_env"), mock.patch.dict("os.environ", {"WARDEN_ALLOWED_SENDERS": ""}):
            self.assertEqual(transfer.default_warden().allowed, set())


class ServerTests(unittest.TestCase):
    TOKEN = "t" * 20

    def setUp(self):
        self.rig = Rig()
        self.server = transfer.serve(self.rig.w, "127.0.0.1", 0, self.TOKEN)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def post(self, body, token=TOKEN, path="/message", raw=None):
        data = raw if raw is not None else json.dumps(body).encode()
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["X-Warden-Token"] = token
        try:
            with urllib.request.urlopen(urllib.request.Request(self.base + path, data, headers), timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read())

    def test_message_round_trip(self):
        status, body = self.post({"sender": ALICE, "text": f"send 0.01 to {A_LOW}"})
        self.assertEqual(status, 200)
        self.assertIn("Reply YES", body["reply"])
        self.assertEqual(self.post({"sender": ALICE, "text": "YES"})[1]["reply"].split("\n")[0][:4], "Sent")
        self.assertEqual(len(self.rig.sent), 1)

    def test_strangers_get_a_null_reply(self):
        self.assertEqual(self.post({"sender": "+10000000000", "text": "hi"}), (200, {"reply": None}))

    def test_token_is_required(self):
        for token in (None, "", "wrong", "t" * 19, "é" * 20):
            status, _ = self.post({"sender": ALICE, "text": "hi"}, token=token)
            self.assertEqual(status, 401, token)
        self.assertEqual(self.rig.audit_calls, [])

    def test_bad_requests(self):
        self.assertEqual(self.post(None, raw=b"not json")[0], 400)
        self.assertEqual(self.post({"sender": 5, "text": "x"})[0], 400)
        self.assertEqual(self.post({"text": "x"})[0], 400)
        self.assertEqual(self.post(None, raw=b"x" * 20000)[0], 413)
        self.assertEqual(self.post({"sender": ALICE, "text": "x"}, path="/other")[0], 404)

    def test_health(self):
        with urllib.request.urlopen(self.base + "/health", timeout=5) as r:
            self.assertEqual(json.loads(r.read()), {"ok": True})


if __name__ == "__main__":
    unittest.main()


class AliasTests(unittest.TestCase):
    AKUL = "0xE54Ea6a50DD6be272aEF623238E5d1DB66e9563B"

    def test_known_alias_resolves_and_auditor_gets_the_address(self):
        rig = Rig()
        ask = rig.say("send 0.01 to Akul.ETH")
        self.assertEqual(rig.audit_calls, [(self.AKUL, 11155111)])
        self.assertIn("akul.eth -> 0xE54E...563B", ask)
        self.assertEqual(rig.say("YES").count("akul.eth -> 0xE54E...563B"), 1)
        self.assertEqual(rig.sent, [(self.AKUL, 10**16)])

    def test_unknown_alias_refuses_without_calling_the_auditor(self):
        rig = Rig()
        self.assertIn("don't know that name", rig.say("send 0.01 to eve.eth"))
        self.assertEqual((rig.audit_calls, rig.sent), ([], []))

    def test_alias_setting_text_changes_nothing(self):
        rig = Rig()
        before = dict(transfer.aliases.ALIASES)
        for text in (f"alias eve.eth = {A_LOW}", f"alias akul.eth = {A_LOW}", "set alias akul.eth = bob"):
            self.assertIn("Nothing changed", rig.say(text))
        self.assertEqual(transfer.aliases.ALIASES, before)
        self.assertEqual((rig.audit_calls, rig.sent), ([], []))

    def test_name_plus_address_is_ambiguous(self):
        rig = Rig()
        self.assertIn("one address or name", rig.say(f"send 0.01 to akul.eth {A_LOW}"))
        self.assertEqual(rig.audit_calls, [])

    def test_btc_is_rejected_even_with_an_alias(self):
        rig = Rig()
        self.assertIn("Ethereum on Sepolia only", rig.say("send 0.01 btc to akul.eth"))
        self.assertEqual(rig.audit_calls, [])

    def test_drainer_alias_is_refused_as_high_and_nothing_is_sent(self):
        drainer = transfer.aliases.resolve("drainer.eth")
        high = {"id": "selfdestruct-opcode", "severity": "high", "message": "bytecode contains a SELFDESTRUCT opcode"}
        rig = Rig(auditor=lambda address, chain: scan_for(address, "HIGH", [high], verified=False, score=65))
        reply = rig.say("send 0.001 to drainer.eth")
        self.assertEqual(rig.audit_calls, [(drainer, 11155111)])
        self.assertIn("Not sent", reply)
        self.assertNotIn("Reply YES", reply)
        self.assertIn("Nothing is waiting", rig.say("YES"))
        self.assertEqual(rig.sent, [])
