"""Etherscan v2 verified-source fetch. One key, many EVM chains via the chainid parameter."""
import json

import requests

API_URL = "https://api.etherscan.io/v2/api"


class EtherscanError(Exception):
    pass


def classify(text):
    """Return ("single", source_text) or ("multi", {path: {"content": ...}})."""
    t = text.strip()
    if t.startswith("{{"):  # standard-json input wrapped in an extra pair of braces
        return "multi", json.loads(t[1:-1])
    if t.startswith("{"):
        try:
            return "multi", json.loads(t)
        except ValueError:
            pass
    return "single", text


def get_source(chain_id, address, api_key, timeout=15):
    """Return {"kind", "source", "compiler", "name"} for verified source, None if unverified.

    Raises EtherscanError on a bad key, rate limit, or network failure. The key is never put in
    error messages.
    """
    params = {"chainid": chain_id, "module": "contract", "action": "getsourcecode",
              "address": address, "apikey": api_key}
    try:
        body = requests.get(API_URL, params=params, timeout=timeout).json()
    except (requests.RequestException, ValueError) as exc:
        raise EtherscanError(f"Etherscan request failed: {type(exc).__name__}") from exc

    result = body.get("result")
    if not isinstance(result, list) or not result:
        raise EtherscanError(f"Etherscan error: {str(result)[:120]}")
    entry = result[0]
    text = entry.get("SourceCode") or ""
    if not text.strip():
        return None
    try:
        kind, source = classify(text)
    except ValueError as exc:
        raise EtherscanError("Etherscan returned unparseable source") from exc
    return {"kind": kind, "source": source, "compiler": entry.get("CompilerVersion"),
            "name": entry.get("ContractName")}
