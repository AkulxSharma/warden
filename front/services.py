"""Where the front end gets its Auditor and Agent.

Defaults to the mocks. When workstreams 1 and 2 land, point these env vars
at their functions (module:function) in .env or the shell. Nothing else in
the front end changes:

    WARDEN_AUDITOR=auditor:audit
    WARDEN_AGENT_REPLY=agent:reply
    WARDEN_AGENT_FOLLOWUP=agent:followup
"""
import importlib
import os

from . import config  # noqa: F401  (loads .env)

DEFAULTS = {
    "WARDEN_AUDITOR": "front.mock_auditor:audit",
    "WARDEN_AGENT_REPLY": "front.mock_agent:reply",
    "WARDEN_AGENT_FOLLOWUP": "front.mock_agent:followup",
}


def _load(var):
    module, _, attr = os.environ.get(var, DEFAULTS[var]).partition(":")
    return getattr(importlib.import_module(module), attr)


def audit(address, chain_id=None, calldata=None, value=None):
    return _load("WARDEN_AUDITOR")(address, chain_id=chain_id, calldata=calldata, value=value)


def agent_reply(result):
    return _load("WARDEN_AGENT_REPLY")(result)


def agent_followup(result, question):
    return _load("WARDEN_AGENT_FOLLOWUP")(result, question)


def using_mocks():
    return {var: os.environ.get(var, default).startswith("front.mock_") for var, default in DEFAULTS.items()}
