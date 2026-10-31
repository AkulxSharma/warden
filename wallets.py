"""Balances, recent transfers, and blocked attempts for the demo wallets. Read-only, Sepolia test ether.

Wallet list lives in wallets.json (public addresses and their aliases, no keys).

A blocked attempt is a transfer the agent REFUSED. It never reached the chain, so it has no
transaction hash and no explorer link. It is read from the bot's events log (kind "refused").
"""
import json
import os
import re
from decimal import Decimal
from pathlib import Path

import requests

import chain
import etherscan

ROOT = Path(__file__).resolve().parent
SEPOLIA = 11155111
EXPLORER = "https://sepolia.etherscan.io"
WEI = Decimal(10) ** 18
EVENTS_DEFAULT = Path.home() / "warden-live" / "data" / "events.jsonl"
SEND_AMOUNT = re.compile(r"\bsend\s+([0-9]*\.?[0-9]+)", re.I)


def load_wallets(path=ROOT / "wallets.json"):
    return json.loads(Path(path).read_text())


def eth(wei):
    return format((Decimal(wei) / WEI).quantize(Decimal("0.000001")), "f")


def balance_wei(address):
    return int(chain.call(SEPOLIA, "eth_getBalance", [address, "latest"]), 16)


def recent_txs(address, api_key, limit=10):
    """Normal transactions for an address, newest first. Raises etherscan.EtherscanError."""
    params = {"chainid": SEPOLIA, "module": "account", "action": "txlist", "address": address,
              "page": 1, "offset": limit, "sort": "desc", "apikey": api_key}
    try:
        body = requests.get(etherscan.API_URL, params=params, timeout=15).json()
    except (requests.RequestException, ValueError) as exc:
        raise etherscan.EtherscanError(f"txlist failed: {type(exc).__name__}") from exc
    result = body.get("result")
    if not isinstance(result, list):
        if "No transactions found" in str(body.get("message", "")):
            return []
        raise etherscan.EtherscanError(f"txlist error: {str(result)[:100]}")
    return result


def blocked_attempts(wallets, events_path=None, limit=10):
    """Refused transfer attempts from the bot's events log, newest last. Empty if there is no log."""
    path = Path(events_path or os.environ.get("WARDEN_EVENTS_PATH") or EVENTS_DEFAULT)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-200:]
    except OSError:
        return []
    if not wallets:
        return []
    alias_of = {w["address"].lower(): w["alias"] for w in wallets}
    main = wallets[0]  # the agent wallet is the sender that would have paid
    out = []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("kind") != "refused":
            continue
        result = event.get("result") or {}
        target = result.get("target")
        amount = SEND_AMOUNT.search(event.get("text") or "")
        verdict = result.get("verdict")
        reason = (f"{verdict} risk ({result.get('riskScore')}/100)" if verdict
                  else "the risk check could not run")
        details = [f["message"] for f in result.get("findings", []) if isinstance(f, dict)][:2]
        out.append({
            "time": int(event.get("ts", 0)), "hash": None,
            "from": main["address"], "to": target,
            "fromAlias": main["alias"], "toAlias": alias_of.get((target or "").lower()),
            "valueEth": amount.group(1) if amount else None,
            "status": "blocked",
            "reason": reason + ("; " + "; ".join(details) if details else ""),
            "explorer": None})
    return out[-limit:]


def snapshot(api_key=None, wallets=None, limit=10, events_path=None):
    """{"chainId", "wallets": [...], "transfers": [...], "transfersError": str|None}.

    transfers holds confirmed or failed on-chain transfers (status "confirmed"/"failed") and
    blocked attempts (status "blocked", never sent), newest first.

    Balances come from the RPC and raise chain.ChainError on failure. The on-chain transfer list
    comes from Etherscan; if that fails the balances and blocked attempts are still returned with
    transfersError set.
    """
    wallets = wallets if wallets is not None else load_wallets()
    api_key = api_key or os.environ.get("ETHERSCAN_API_KEY")
    alias_of = {w["address"].lower(): w["alias"] for w in wallets}
    target_addrs = {w["address"].lower() for w in wallets if w.get("kind") == "target"}

    out_wallets = [{"alias": w["alias"], "role": w.get("role", ""), "kind": w.get("kind", "wallet"),
                    "address": w["address"],
                    "balanceEth": eth(balance_wei(w["address"])),
                    "explorer": f"{EXPLORER}/address/{w['address']}"} for w in wallets]

    transfers, error, seen = [], None, set()
    if not api_key:
        error = "no Etherscan key configured"
    else:
        try:
            for w in wallets:
                if w.get("kind") == "target":
                    continue  # demo targets only receive; their funding shows in the main wallet's list
                for tx in recent_txs(w["address"], api_key, limit):
                    if tx["hash"] in seen or int(tx["value"]) == 0:
                        continue
                    if tx.get("isError") != "0" and (tx["to"] or "").lower() in target_addrs:
                        continue  # a reverted top-up of a demo target is setup noise, not an agent transfer
                    seen.add(tx["hash"])
                    transfers.append({
                        "time": int(tx["timeStamp"]), "hash": tx["hash"],
                        "from": tx["from"], "to": tx["to"],
                        "fromAlias": alias_of.get(tx["from"].lower()),
                        "toAlias": alias_of.get((tx["to"] or "").lower()),
                        "valueEth": eth(int(tx["value"])),
                        "status": "confirmed" if tx.get("isError") == "0" else "failed",
                        "explorer": f"{EXPLORER}/tx/{tx['hash']}"})
        except etherscan.EtherscanError as exc:
            error = str(exc)
    transfers += blocked_attempts(wallets, events_path, limit)
    transfers.sort(key=lambda t: t["time"], reverse=True)
    return {"chainId": SEPOLIA, "wallets": out_wallets, "transfers": transfers[:limit],
            "transfersError": error}
