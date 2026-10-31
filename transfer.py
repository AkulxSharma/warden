#!/usr/bin/env python3
"""Warden transfer agent: the flow between iMessage and the chain.

    handle_message(sender, text) -> reply string, or None to stay silent

A message is a transfer ("send 0.01 to 0x..."), a screen ("0x..."), a confirmation ("YES"),
or a follow-up question about the last scan. The gate is plain code: the Auditor's result
decides, the language model only words replies (agent.py) and can never trigger a send.
Sepolia test ETH only. Anything unclear, failed or unverifiable means no send.

    python3 transfer.py chat    # try it in the terminal (you are sender "local")
    python3 transfer.py serve   # HTTP for the iMessage side: POST /message {"sender","text"}
                                # with header X-Warden-Token; needs WARDEN_AGENT_TOKEN

Settings (env or .env): WARDEN_ALLOWED_SENDERS (comma list of handles), WARDEN_AUDITOR_URL,
WARDEN_USE_FIXTURES=1 (demo: addresses starting 0x1/0x2/0x3 use Akul's LOW/MEDIUM/HIGH
fixtures), SEPOLIA_PRIVATE_KEY, SEPOLIA_RPC_URL, WARDEN_MAX_ETH, ANTHROPIC_API_KEY.
"""
import hmac
import json
import logging
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import agent
import wallet

log = logging.getLogger("warden.transfer")

CHAIN_ID = wallet.SEPOLIA
PENDING_TTL = 300        # seconds a YES stays valid
AUDITOR_TIMEOUT = 20     # seconds before the check counts as failed
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "auditor-output"

HELP = ("Text an address to screen it, or 'send 0.01 to 0x...' to send Sepolia test ETH "
        "after a risk check. Reply YES to confirm a send.")
OOPS = "Something went wrong on my side. Please try again."
DEMO_LABEL = " (demo data: Auditor not connected)"

ADDR = re.compile(r"(?<![0-9A-Za-z])0x[0-9a-fA-F]{40}(?![0-9A-Za-z])")
VERB = re.compile(r"\b(?:send|transfer|pay)\b", re.I)
NUMBER = re.compile(r"(?<![\w.\-])(?:\d+(?:\.\d+)?|\.\d+)(?!\w|\.\d)")
OTHER_ASSET = re.compile(
    r"\b(?:usdc|usdt|dai|usd|dollars?|bucks|btc|bitcoin|sol|solana|wei|gwei|bnb|matic|weth|steth)\b"
    r"|[$€£]", re.I)
OTHER_CHAIN = re.compile(
    r"\b(?:mainnet|base|polygon|arbitrum|optimism|avalanche|bsc|solana|goerli|holesky)\b", re.I)

SCAN_KEYS = {"target", "chainId", "verdict", "riskScore", "verified", "findings"}
FINDING_KEYS = {"id", "severity", "message"}


class AuditorError(Exception):
    pass


def norm_handle(handle):
    """Phone numbers compare by digits, everything else by lowercase text."""
    text = str(handle).strip().lower()
    digits = re.sub(r"[\s().\-]", "", text)
    return digits if re.fullmatch(r"\+?\d{7,15}", digits) else text


def parse_intent(text):
    """Classify a message: yes, no, transfer, screen, question, help, or bad (with an error)."""
    t = " ".join(str(text).split())
    if not t:
        return {"kind": "help"}
    if re.fullmatch(r"yes[.!]*", t, re.I):
        return {"kind": "yes"}
    if re.fullmatch(r"(?:no|cancel|stop)[.!]*", t, re.I):
        return {"kind": "no"}

    def bad(error):
        return {"kind": "bad", "error": error}

    addresses = ADDR.findall(t)
    if len(addresses) > 1:
        return bad("I can only handle one address at a time.")
    if not addresses:
        return {"kind": "question", "text": t}
    rest = ADDR.sub(" ", t)
    if OTHER_CHAIN.search(rest):
        return bad("I only work on Sepolia test ETH right now.")
    if not VERB.search(rest):
        return {"kind": "screen", "address": addresses[0]}
    if OTHER_ASSET.search(rest):
        return bad("I only send Sepolia test ETH.")
    numbers = NUMBER.findall(rest)
    if not numbers:
        return bad("How much? Example: send 0.01 to 0x...")
    if len(numbers) > 1:
        return bad("I found more than one amount. Example: send 0.01 to 0x...")
    amount = Decimal(numbers[0]).normalize()
    if amount <= 0:
        return bad("The amount must be above zero.")
    if -amount.as_tuple().exponent > 18:
        return bad("That amount has too many decimal places.")
    return {"kind": "transfer", "address": addresses[0], "amount": amount}


def address_problem(address):
    """A reason to refuse this address before any check, or None."""
    if int(address, 16) == 0:
        return "That is the zero address, which would burn the funds."
    digits = address[2:]
    if digits != digits.lower() and digits != digits.upper():  # mixed case must be a valid checksum
        try:
            from eth_utils import is_checksum_address
        except ImportError:
            return None
        if not is_checksum_address(address):
            return "That address fails its checksum, so it may have a typo. Please check it."
    return None


def check_scan(scan):
    """True when scan matches schema/auditor-output.schema.json (slightly stricter: no float integers)."""
    if not isinstance(scan, dict) or set(scan) != SCAN_KEYS:
        return False
    target, chain = scan["target"], scan["chainId"]
    score = scan["riskScore"]
    if not (isinstance(target, str) and wallet.ADDRESS.fullmatch(target)):
        return False
    if type(chain) is not int or chain < 1:
        return False
    if scan["verdict"] not in ("LOW", "MEDIUM", "HIGH"):
        return False
    if type(score) is not int or not 0 <= score <= 100:
        return False
    if type(scan["verified"]) is not bool or not isinstance(scan["findings"], list):
        return False
    return all(
        isinstance(f, dict) and set(f) == FINDING_KEYS and isinstance(f["id"], str)
        and f["severity"] in ("high", "medium", "low") and isinstance(f["message"], str)
        for f in scan["findings"])


def gate(scan):
    """The send decision for a schema-valid scan: 'refuse' or 'confirm'.
    Takes the worse of the verdict and the worst finding, so an inconsistent Auditor cannot
    wave a high finding through."""
    if scan["verdict"] == "HIGH" or any(f["severity"] == "high" for f in scan["findings"]):
        return "refuse"
    return "confirm"


def http_auditor(base_url, timeout=AUDITOR_TIMEOUT):
    base = base_url.strip().rstrip("/")
    if not re.match(r"https?://", base):
        raise ValueError("WARDEN_AUDITOR_URL must start with http:// or https://")

    def call(address, chain_id):
        query = urllib.parse.urlencode({"address": address, "chainId": chain_id})
        req = urllib.request.Request(
            f"{base}/screen?{query}", headers={"User-Agent": "warden-agent/1.0", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as response:  # non-2xx raises
            if response.status != 200:
                raise AuditorError(f"HTTP {response.status}")
            return json.loads(response.read(1_000_000))
    return call


def fixture_auditor(directory=FIXTURE_DIR):
    names = {"1": "low", "2": "medium", "3": "high"}

    def call(address, chain_id):
        name = names.get(address[2])
        if name is None:
            raise AuditorError("demo mode: only addresses starting 0x1, 0x2 or 0x3 have a fixture")
        scan = json.loads((Path(directory) / f"{name}.json").read_text(encoding="utf-8"))
        scan["target"], scan["chainId"] = address, chain_id
        return scan
    return call


def no_auditor(address, chain_id):
    raise AuditorError("no Auditor is configured")


def short(address):
    return f"{address[:6]}...{address[-4:]}"


@dataclass
class Pending:
    address: str
    wei: int
    created: float


class Warden:
    """One instance holds the pending requests and the last scan per sender."""

    def __init__(self, allowed, auditor, send, clock=time.time, demo=False,
                 explain=agent.explain, answer=agent.answer):
        self.allowed = {norm_handle(h) for h in allowed}
        self.auditor, self.send, self.clock, self.demo = auditor, send, clock, demo
        self.explain, self.answer = explain, answer
        self._send_lock = threading.Lock()
        self.pending = {}  # sender -> Pending, one per sender
        self.last = {}     # sender -> {"scan", "history"} for follow-up questions

    def handle(self, sender, text):
        """Reply text, or None when the sender is not on the allowlist. Never raises."""
        who = norm_handle(sender)
        if who not in self.allowed:
            return None
        try:
            return self._handle(who, text)
        except Exception:
            log.exception("handle failed")
            return OOPS

    def _handle(self, who, text):
        intent = parse_intent(text)
        kind = intent["kind"]
        if kind == "help":
            return HELP
        if kind == "yes":
            return self._confirm(who)
        if kind == "no":
            return "Cancelled. Nothing was sent." if self.pending.pop(who, None) else "Nothing to cancel."
        if kind == "question":
            return self._followup(who, intent["text"])

        # Anything else is about an address. It replaces any older pending request even when it is
        # refused below, so a later YES can only confirm the request the user saw last.
        self.pending.pop(who, None)
        if kind == "bad":
            return intent["error"]
        address = intent["address"]
        problem = address_problem(address)
        if problem:
            return problem
        wei = 0
        if kind == "transfer":
            wei = int(intent["amount"].scaleb(18))
            if wei > wallet.max_wei():
                return f"That is above my limit of {wallet.format_eth(wallet.max_wei())} ETH per transfer."
        scan = self._audit(address)
        if scan is None:
            return ("I couldn't run the risk check, so I did not send anything. Please try again in a minute."
                    if kind == "transfer" else "I couldn't run the risk check. Please try again in a minute.")
        self.last[who] = {"scan": scan, "history": []}
        label = DEMO_LABEL if self.demo else ""
        if kind == "screen":
            return self.explain(scan, note=label.strip())
        if gate(scan) == "refuse":
            return self.explain(scan, note="Not sent: I won't send to an address with this risk signal." + label)
        reply = self.explain(scan, note=(
            f"Send {wallet.format_eth(wei)} ETH to {short(address)} on Sepolia? "
            f"Reply YES within {PENDING_TTL // 60} min to send, or NO to cancel." + label))
        self.pending[who] = Pending(address, wei, self.clock())  # only once the user has been asked
        return reply

    def _audit(self, address):
        """A schema-valid scan of exactly this address and chain, or None."""
        try:
            scan = self.auditor(address, CHAIN_ID)
        except Exception as e:  # timeout, HTTP error, bad JSON, no Auditor: the check could not run
            log.warning("auditor failed: %s", e)
            return None
        if not check_scan(scan):
            log.warning("auditor result failed the schema")
            return None
        if scan["target"].lower() != address.lower() or scan["chainId"] != CHAIN_ID:
            log.warning("auditor result is for a different address or chain")
            return None
        return scan

    def _confirm(self, who):
        pending = self.pending.pop(who, None)  # pop first: a repeated YES can never send twice
        if pending is None:
            return "Nothing is waiting for confirmation. Text an address to screen it, or 'send 0.01 to 0x...'."
        if self.clock() - pending.created > PENDING_TTL:
            return "That request expired. Please send it again."
        try:
            with self._send_lock:  # one send at a time, so two senders cannot reuse a nonce
                tx_hash = self.send(pending.address, pending.wei)
        except wallet.SendError as e:
            if e.tx_hash:
                return (f"The transfer may have gone out but I could not confirm it. "
                        f"Check {wallet.EXPLORER_TX}{e.tx_hash} before trying again.")
            return f"The transfer failed: {e}. Nothing was sent."
        return f"Sent {wallet.format_eth(pending.wei)} ETH to {short(pending.address)} on Sepolia.\n{wallet.EXPLORER_TX}{tx_hash}"

    def _followup(self, who, text):
        last = self.last.get(who)
        if last is None:
            return HELP
        reply = self.answer(last["scan"], text, last["history"])
        last["history"].append((text, reply))
        del last["history"][:-agent.HISTORY_PAIRS]
        return reply


def default_warden():
    """A Warden configured from the environment (and .env). Fails closed without an Auditor."""
    wallet.load_env()
    allowed = [h for h in os.environ.get("WARDEN_ALLOWED_SENDERS", "").split(",") if h.strip()]
    url = os.environ.get("WARDEN_AUDITOR_URL", "").strip()
    demo = False
    if url:
        auditor = http_auditor(url)
    elif os.environ.get("WARDEN_USE_FIXTURES") == "1":
        auditor, demo = fixture_auditor(), True
    else:
        auditor = no_auditor
    return Warden(allowed, auditor, wallet.send_eth, demo=demo)


_default = None


def handle_message(sender, text):
    """Entry point for the iMessage side. Returns the reply text, or None to stay silent."""
    global _default
    if _default is None:
        _default = default_warden()
    return _default.handle(sender, text)


def serve(warden, host, port, token):
    secret = token.encode()

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._send(200, {"ok": True}) if self.path == "/health" else self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/message":
                return self._send(404, {"error": "not found"})
            if not hmac.compare_digest(self.headers.get("X-Warden-Token", "").encode(), secret):
                return self._send(401, {"error": "unauthorized"})
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if not 0 < length <= 10_000:
                    return self._send(413, {"error": "bad size"})
                body = json.loads(self.rfile.read(length))
                sender, text = body["sender"], body["text"]
                if not (isinstance(sender, str) and isinstance(text, str)):
                    raise TypeError
            except (ValueError, KeyError, TypeError):
                return self._send(400, {"error": "expected JSON with string sender and text"})
            self._send(200, {"reply": warden.handle(sender, text)})

        def log_message(self, *args):  # never log request lines, bodies or headers
            pass

    server = ThreadingHTTPServer((host, port), Handler)
    return server


def main(argv):
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    command = argv[0] if argv else ""
    if command == "chat":
        warden = default_warden()
        if warden.auditor is no_auditor:
            warden.auditor, warden.demo = fixture_auditor(), True
        warden.allowed.add("local")
        print("Warden chat. Demo addresses: 0x1111111111111111111111111111111111111111 (LOW), "
              "0x2222222222222222222222222222222222222222 (MEDIUM), 0x3333333333333333333333333333333333333333 (HIGH).")
        while True:
            try:
                line = input("you> ")
            except EOFError:
                return 0
            print(warden.handle("local", line) or "(ignored)")
    if command == "serve":
        warden = default_warden()
        token = os.environ.get("WARDEN_AGENT_TOKEN", "")
        if len(token) < 16:
            print("Set WARDEN_AGENT_TOKEN (16+ characters) first: the endpoint can trigger transfers.")
            return 1
        if not warden.allowed:
            print("Warning: WARDEN_ALLOWED_SENDERS is empty, so every sender will be ignored.")
        host, port = os.environ.get("WARDEN_AGENT_HOST", "127.0.0.1"), int(os.environ.get("WARDEN_AGENT_PORT", "8787"))
        print(f"Listening on http://{host}:{port} (POST /message, GET /health)")
        serve(warden, host, port, token).serve_forever()
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
