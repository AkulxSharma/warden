"""One message in, one reply out. Shared by the iMessage bot and the dashboard.

Flow (PRODUCT-DEV-DOC section 2):
  "send 0.01 to 0x.."  -> Auditor -> gate (code, never the model):
                          HIGH or a failed check -> refuse with reasons
                          LOW / MEDIUM -> "Reply YES to send", pending per conversation
  "YES"                -> send the pending transfer (only for can_transfer senders)
  "0x.."               -> screen only
  anything else        -> follow-up about the last scan, or help

Every exchange is appended to data/events.jsonl for the dashboard's live feed.
"""
import hashlib
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

import aliases
import transfer

from . import services
from .parse import SEPOLIA, chain_name, parse

EVENTS = Path(__file__).resolve().parent.parent / "data" / "events.jsonl"
PENDING_TTL = 300   # seconds a YES stays valid
EXPLORER_TX = "https://sepolia.etherscan.io/tx/"

HELP = ("Warden checks an address before you pay it.\n"
        "Text \"send 0.01 to 0x…\" and I'll screen the address first: HIGH risk gets refused, "
        "otherwise I ask you to confirm. Or just text an address to screen it.\n"
        "Sepolia testnet only. Risk signal, not a guarantee.")
ASK_ADDRESS = "Send me a 0x address to screen, or \"send 0.01 to 0x…\"."
TX_HASH = "That looks like a transaction hash. Send the address you're about to pay instead."
ENS = "I don't know that name. Send the 0x address instead."
LINK_NO_ADDRESS = "I couldn't find an address in that link. Send the 0x address or an explorer link with one."
CHECK_FAILED = "Refused: the risk check could not run, so nothing was sent. Try again in a minute."
SCAN_FAILED = "The risk check could not run right now. Try again in a minute."
NO_PENDING = "There's nothing waiting for a YES. Text \"send 0.01 to 0x…\" to start."
CANCELLED = "Cancelled. Nothing was sent."
EXPIRED = "That request expired, so nothing was sent. Send it again to re-check the address."
NO_AMOUNT = "How much? Text it like \"send 0.01 to 0x…\" (Sepolia ETH)."
NOT_ALLOWED = ("\n\nTransfers are limited to the team's test phones, so this was a risk check only. "
               "Nothing was sent.")
DEMO_SENT = ("Confirmed, and the risk gate passed. Demo mode: no test wallet is connected, "
             "so no transaction was sent.")
SEND_FAILED = "The transfer failed, so nothing was sent: {}"

_sessions = {}   # conversation -> {"result", "history", "pending"}
_lock = threading.Lock()


def max_send():
    return float(os.environ.get("WARDEN_MAX_SEND_ETH", "0.01"))


def gate(result, address, chain_id=SEPOLIA):
    """The send decision, in code. result is the Auditor dict, or None if the check failed.
    Delegates to transfer.gate so there is one gate: a schema-invalid result, a result for another
    address or chain, a HIGH verdict, or any high-severity finding all refuse."""
    if (result is None or not transfer.check_scan(result)
            or result["target"].lower() != address.lower() or result["chainId"] != chain_id):
        return "refuse"
    return transfer.gate(result)


def name_of(address):
    """Alias (andrew.eth) if the address has one, else the short form."""
    for alias, addr in aliases.ALIASES.items():
        if addr.lower() == (address or "").lower():
            return alias
    return short(address)


def _stage(state, stage, **fields):
    """Progress-tracker event (UI-PROGRESS-SPEC.md). Stage names are a contract."""
    _log({"ts": time.time(), "convo": state["convo"], "stage": stage, **fields})


def _reasons(result):
    return [f["message"] for f in result.get("findings", [])][:3]


def short(address):
    return f"{address[:6]}…{address[-4:]}"


def _log(event):
    EVENTS.parent.mkdir(exist_ok=True)
    with _lock, EVENTS.open("a") as f:
        f.write(json.dumps(event) + "\n")


def _screen(address, chain_id):
    """(result, error). Never raises."""
    try:
        return services.audit(address, chain_id=chain_id), None
    except services.AuditorError as exc:
        print(f"[warden] auditor failed: {exc}", file=sys.stderr)
        return None, str(exc)


def _transfer(parsed, state, can_transfer):
    if parsed.amount is None:
        return "need_amount", NO_AMOUNT, None
    if parsed.amount <= 0 or parsed.amount > max_send():
        return "blocked_amount", f"Transfers are capped at {max_send():g} Sepolia ETH for this demo.", None
    target, amount = name_of(parsed.address), f"{parsed.amount:g}"
    _stage(state, "received", target=target, amountEth=amount)
    _stage(state, "screening", target=target, amountEth=amount)
    result, _ = _screen(parsed.address, SEPOLIA)
    if result:
        state["result"], state["history"] = result, []
        _stage(state, "screening", target=target, amountEth=amount, verdict=result["verdict"],
               riskScore=result["riskScore"], reasons=_reasons(result))
    if gate(result, parsed.address) == "refuse":
        state["pending"] = None
        _stage(state, "refused", target=target, amountEth=amount,
               verdict=result and result["verdict"], riskScore=result and result["riskScore"],
               reasons=_reasons(result) if result else ["The risk check could not run."])
        if result is None:
            return "refused", CHECK_FAILED, None
        return "refused", (f"Refused: not sending {parsed.amount:g} ETH to {short(parsed.address)}.\n\n"
                           + services.agent_reply(result)), result
    reply = services.agent_reply(result)
    if not can_transfer:
        _stage(state, "screened", target=target, amountEth=amount, verdict=result["verdict"],
               riskScore=result["riskScore"], reasons=_reasons(result))
        return "screened", reply + NOT_ALLOWED, result
    state["pending"] = {"to": parsed.address, "amount": parsed.amount, "ts": time.time()}
    _stage(state, "awaiting_confirmation", target=target, amountEth=amount,
           verdict=result["verdict"], riskScore=result["riskScore"])
    return "confirm", (f"{reply}\n\nReply YES to send {parsed.amount:g} Sepolia ETH to "
                       f"{short(parsed.address)}, or NO to cancel."), result


def _confirm(state):
    pending, state["pending"] = state.get("pending"), None
    if not pending:
        return "yes_nothing", NO_PENDING
    info = {"target": name_of(pending["to"]), "amountEth": f"{pending['amount']:g}"}
    if time.time() - pending["ts"] > PENDING_TTL:
        _stage(state, "expired", **info)
        return "expired", EXPIRED
    if not services.transfer_enabled():
        _stage(state, "paid", txHash=None, demo=True, **info)
        return "demo_sent", DEMO_SENT
    try:
        tx = services.send_transfer(pending["to"], pending["amount"])
    except Exception as exc:  # report the failure, never claim a send
        print(f"[warden] transfer failed: {exc!r}", file=sys.stderr)
        _stage(state, "failed", reason=type(exc).__name__, **info)
        return "send_failed", SEND_FAILED.format(type(exc).__name__)
    _stage(state, "paid", txHash=tx, **info)
    return "sent", (f"Sent {pending['amount']:g} Sepolia ETH to {short(pending['to'])}.\n"
                    f"{EXPLORER_TX}{tx}")


def handle_message(text, session="default", channel="web", sender="you", can_transfer=False):
    """Return {"reply": str, "result": dict | None, "kind": str}."""
    parsed = parse(text)
    state = _sessions.setdefault(session, {"result": None, "history": [], "pending": None,
                                           "convo": hashlib.sha256(session.encode()).hexdigest()[:10]})
    result = None
    kind = parsed.kind

    if parsed.kind in ("scan", "transfer") and (parsed.chain_id or SEPOLIA) != SEPOLIA:
        kind = "blocked_chain"
        reply = (f"Warden only works on Sepolia testnet right now, so I didn't check this "
                 f"{chain_name(parsed.chain_id)} address. Send a Sepolia address.")
    elif parsed.kind == "transfer":
        kind, reply, result = _transfer(parsed, state, can_transfer)
    elif parsed.kind == "scan":
        result, _ = _screen(parsed.address, SEPOLIA)
        if result:
            state["result"], state["history"] = result, []
            reply = services.agent_reply(result)
            if parsed.extra_addresses:
                reply += f"\n\n(I checked the first address. Send the other {len(parsed.extra_addresses)} separately.)"
        else:
            kind, reply = "error", SCAN_FAILED
    elif parsed.kind == "yes":
        kind, reply = _confirm(state) if can_transfer else ("yes_nothing", NO_PENDING)
    elif parsed.kind == "no":
        if state.get("pending"):
            _stage(state, "cancelled", target=name_of(state["pending"]["to"]),
                   amountEth=f"{state['pending']['amount']:g}")
        kind, reply = "cancelled", CANCELLED if state.get("pending") else NO_PENDING
        state["pending"] = None
    elif parsed.kind == "text" and state["result"]:
        kind, result = "followup", state["result"]
        reply = services.agent_followup(result, text, list(state["history"]))
        state["history"].append((text, reply))
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
