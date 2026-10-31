"""Minimal JSON-RPC client for the Auditor. Sepolia only until told otherwise."""
import os

import requests


class ChainError(Exception):
    pass


DEFAULT_RPC = {11155111: "https://ethereum-sepolia-rpc.publicnode.com"}


def rpc_url(chain_id):
    url = os.environ.get(f"RPC_URL_{chain_id}") or DEFAULT_RPC.get(chain_id)
    if not url:
        raise ChainError(f"no RPC configured for chainId {chain_id} (Sepolia only until told otherwise)")
    return url


def call(chain_id, method, params, timeout=10):
    url = rpc_url(chain_id)
    try:
        res = requests.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                            timeout=timeout)
        res.raise_for_status()
        body = res.json()
    except (requests.RequestException, ValueError) as exc:
        raise ChainError(f"RPC {method} failed: {type(exc).__name__}") from exc
    if "error" in body:
        raise ChainError(f"RPC {method} error: {str(body['error'])[:120]}")
    return body["result"]


def get_code(chain_id, address):
    return bytes.fromhex(call(chain_id, "eth_getCode", [address, "latest"])[2:])


def get_storage_at(chain_id, address, slot):
    return bytes.fromhex(call(chain_id, "eth_getStorageAt", [address, slot, "latest"])[2:])
