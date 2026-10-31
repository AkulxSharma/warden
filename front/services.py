"""Where the front end gets its Auditor, Agent wording and transfer sender.

Set in .env or the shell; nothing else in the front end changes:

    WARDEN_AUDITOR_URL=https://...        live Auditor: GET <url>/screen?address=..&chainId=..
    WARDEN_AUDITOR=front.mock_auditor:audit   in-process Auditor when no URL is set
    WARDEN_AGENT_REPLY=agent:explain      reply(scan) -> str
    WARDEN_AGENT_FOLLOWUP=agent:answer    followup(scan, question, history) -> str
    WARDEN_TRANSFER=module:send           send(to, amount_eth) -> tx hash; unset = demo mode
"""
import importlib
import json
import os
import urllib.parse
import urllib.request

from . import config  # noqa: F401  (loads .env)

DEFAULTS = {
    "WARDEN_AUDITOR": "front.mock_auditor:audit",
    "WARDEN_AGENT_REPLY": "agent:explain",
    "WARDEN_AGENT_FOLLOWUP": "agent:answer",
    "WARDEN_TRANSFER": "",
}
AUDITOR_TIMEOUT = 20  # seconds; a timeout counts as a failed check, which refuses
KEYS = {"target", "chainId", "verdict", "riskScore", "verified", "findings"}


class AuditorError(Exception):
    """The check could not run. The gate treats this as a refusal."""


def _load(var):
    spec = os.environ.get(var, DEFAULTS[var])
    if not spec:
        return None
    module, _, attr = spec.partition(":")
    return getattr(importlib.import_module(module), attr)


def _check(result):
    ok = (isinstance(result, dict) and KEYS <= set(result)
          and result["verdict"] in {"LOW", "MEDIUM", "HIGH"}
          and type(result["riskScore"]) is int and 0 <= result["riskScore"] <= 100
          and isinstance(result["verified"], bool) and isinstance(result["findings"], list))
    if not ok:
        raise AuditorError("Auditor returned JSON that does not match the contract")
    return result


def audit(address, chain_id=None, calldata=None, value=None):
    """Auditor result dict. Raises AuditorError on any failure (error, timeout, bad JSON)."""
    base = os.environ.get("WARDEN_AUDITOR_URL", "").rstrip("/")
    try:
        if base:
            query = urllib.parse.urlencode({"address": address, "chainId": chain_id or 11155111})
            with urllib.request.urlopen(f"{base}/screen?{query}", timeout=AUDITOR_TIMEOUT) as r:
                return _check(json.load(r))
        return _check(_load("WARDEN_AUDITOR")(address, chain_id=chain_id, calldata=calldata, value=value))
    except AuditorError:
        raise
    except Exception as exc:
        raise AuditorError(repr(exc)) from exc


def agent_reply(result):
    return _load("WARDEN_AGENT_REPLY")(result)


def agent_followup(result, question, history=()):
    fn = _load("WARDEN_AGENT_FOLLOWUP")
    try:
        return fn(result, question, history)
    except TypeError:  # the mock takes no history
        return fn(result, question)


def transfer_enabled():
    return bool(os.environ.get("WARDEN_TRANSFER"))


def send_transfer(to, amount_eth):
    """Tx hash string. Only called after the gate passed and the sender replied YES."""
    return _load("WARDEN_TRANSFER")(to, amount_eth)


def status():
    return {
        "auditor": "live" if os.environ.get("WARDEN_AUDITOR_URL") else
                   ("mock" if os.environ.get("WARDEN_AUDITOR", DEFAULTS["WARDEN_AUDITOR"]).startswith("front.mock_") else "local"),
        "agent": "mock" if os.environ.get("WARDEN_AGENT_REPLY", DEFAULTS["WARDEN_AGENT_REPLY"]).startswith("front.mock_") else "real",
        "transfers": "on" if transfer_enabled() else "demo",
    }
