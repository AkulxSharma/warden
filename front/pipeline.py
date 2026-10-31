"""One message in, one reply out. Shared by the iMessage bot and the dashboard.

Keeps the last scan per conversation so follow-up questions work, and appends
every exchange to data/events.jsonl so the dashboard can show the live feed.
"""
import json
import re
import sys
import threading
import time
from pathlib import Path

from . import services
from .parse import SEPOLIA, chain_name, parse

EVENTS = Path(__file__).resolve().parent.parent / "data" / "events.jsonl"

HELP = ("Warden screens an address before you pay it.\n"
        "Text me a 0x address or an explorer link (Sepolia testnet for now), "
        "and I'll reply with a risk signal and the reasons.\n"
        "Risk signal, not a guarantee.")
ASK_ADDRESS = "Send me a 0x address (40 hex characters) or an explorer link and I'll scan it."
TX_HASH = "That looks like a transaction hash. Send the address you're about to pay instead."
ENS = "ENS names aren't supported yet. Send the 0x address instead."
LINK_NO_ADDRESS = "I couldn't find an address in that link. Send the 0x address or an explorer link with one."
SCAN_FAILED = "I couldn't scan that address right now. Try again in a minute."

_sessions = {}
_lock = threading.Lock()


def _chain_blocked(chain_id):
    return (f"Warden only scans Sepolia testnet right now, so I didn't scan this "
            f"{chain_name(chain_id)} address. Send a Sepolia address.")


def _log(event):
    EVENTS.parent.mkdir(exist_ok=True)
    with _lock, EVENTS.open("a") as f:
        f.write(json.dumps(event) + "\n")


def handle_message(text, session="default", channel="web", sender="you"):
    """Return {"reply": str, "result": dict | None, "kind": str}."""
    parsed = parse(text)
    result = None
    kind = parsed.kind

    if parsed.kind == "scan":
        chain_id = parsed.chain_id or SEPOLIA
        if chain_id != SEPOLIA:
            kind, reply = "blocked_chain", _chain_blocked(chain_id)
        else:
            try:
                result = services.audit(parsed.address, chain_id=chain_id)
                reply = services.agent_reply(result)
                _sessions[session] = result
            except Exception as exc:  # the user still gets an answer
                print(f"[warden] scan failed: {exc!r}", file=sys.stderr)
                kind, reply = "error", SCAN_FAILED
            if result and parsed.extra_addresses:
                reply += f"\n\n(I scanned the first address. Send the other {len(parsed.extra_addresses)} separately.)"
    elif parsed.kind == "text" and session in _sessions:
        kind, result = "followup", _sessions[session]
        reply = services.agent_followup(result, text)
    else:
        reply = {"help": HELP, "tx_hash": TX_HASH, "ens": ENS,
                 "link_no_address": LINK_NO_ADDRESS}.get(parsed.kind, ASK_ADDRESS)
        if parsed.kind == "text":
            reply = HELP if len(text.split()) > 3 else ASK_ADDRESS

    if re.search(r"\bsafe\b", reply, re.I):
        print("[warden] WARNING: reply contains the word 'safe'", file=sys.stderr)

    _log({"ts": time.time(), "channel": channel, "sender": sender, "text": text,
          "reply": reply, "kind": kind, "result": result})
    return {"reply": reply, "result": result, "kind": kind}


def read_events(after=0):
    """Events with index >= after, each tagged with its index."""
    if not EVENTS.exists():
        return []
    out = []
    for i, line in enumerate(EVENTS.read_text().splitlines()):
        if i >= after and line.strip():
            event = json.loads(line)
            event["i"] = i
            out.append(event)
    return out
