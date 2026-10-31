#!/usr/bin/env python3
"""Sepolia wallet for the transfer agent. Test ETH only.

The private key comes from SEPOLIA_PRIVATE_KEY (in .env, never in the repo, a log or a
message). Every send is checked first: the RPC must report Sepolia, the amount must be
within the per-transfer cap, the wallet must cover amount plus gas, and a gas estimate
must not revert.

    python3 wallet.py new-wallet   # make a throwaway key, save it to .env, print only the address
    python3 wallet.py address      # print the wallet address
    python3 wallet.py balance      # print the Sepolia balance
"""
import json
import os
import re
import sys
import urllib.request
from decimal import Decimal, InvalidOperation
from pathlib import Path

SEPOLIA = 11155111
DEFAULT_RPC = "https://ethereum-sepolia-rpc.publicnode.com"
EXPLORER_TX = "https://sepolia.etherscan.io/tx/"
DEFAULT_MAX_ETH = Decimal("0.01")
WEI = 10 ** 18
GWEI = 10 ** 9
RPC_TIMEOUT = 10
ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}")
ENV_PATH = Path(__file__).resolve().parent / ".env"


class SendError(Exception):
    """A send failed. str(e) is safe to show a user and never contains the key.
    tx_hash is set only when the transaction may already have been broadcast."""

    def __init__(self, message, tx_hash=None):
        super().__init__(message)
        self.tx_hash = tx_hash


def load_env(path=ENV_PATH):
    """Read KEY=VALUE lines into os.environ without overriding what is already set."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def max_wei():
    """Hard per-transfer cap. WARDEN_MAX_ETH overrides the 0.01 ETH default."""
    try:
        eth = Decimal(os.environ.get("WARDEN_MAX_ETH", ""))
    except InvalidOperation:
        eth = DEFAULT_MAX_ETH
    if not eth.is_finite() or eth <= 0:
        eth = DEFAULT_MAX_ETH
    return int(eth.scaleb(18))


def format_eth(wei):
    return format(Decimal(wei).scaleb(-18).normalize(), "f")


def rpc_url():
    url = (os.environ.get("SEPOLIA_RPC_URL") or DEFAULT_RPC).strip()
    if not re.match(r"https?://", url):
        raise SendError("the RPC URL is not valid")
    return url


def _rpc(url, method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(
        url, body, {"Content-Type": "application/json", "User-Agent": "warden-agent/1.0"})
    with urllib.request.urlopen(req, timeout=RPC_TIMEOUT) as response:
        reply = json.loads(response.read(2_000_000))
    if "error" in reply:
        error = reply["error"]
        raise RuntimeError(error.get("message", "rpc error") if isinstance(error, dict) else str(error))
    return reply["result"]


def _account():
    key = os.environ.get("SEPOLIA_PRIVATE_KEY", "").strip()
    if not key:
        raise SendError("the sending wallet is not set up")
    try:
        from eth_account import Account
        return Account.from_key(key)
    except ImportError:
        raise SendError("the signing library is not installed") from None
    except Exception:  # message could echo key material, so say nothing about it
        raise SendError("the sending wallet key is not valid") from None


def wallet_address():
    return _account().address


def _hex(raw):
    return "0x" + bytes(raw).hex()


def send_eth(to, amount_wei, chain_id=SEPOLIA):
    """Sign and broadcast a plain ETH transfer on Sepolia. Returns the tx hash. Raises SendError."""
    if chain_id != SEPOLIA:
        raise SendError("this agent only sends on Sepolia")
    if type(amount_wei) is not int or not 0 < amount_wei <= max_wei():
        raise SendError("the amount is outside the allowed limit")
    if not ADDRESS.fullmatch(str(to)):
        raise SendError("the address is not valid")
    account = _account()
    url = rpc_url()
    try:
        from eth_account import Account
        from eth_utils import to_checksum_address
        recipient = to_checksum_address(to)
        if int(_rpc(url, "eth_chainId", []), 16) != SEPOLIA:
            raise SendError("the RPC is not Sepolia, so I did not send")
        nonce = int(_rpc(url, "eth_getTransactionCount", [account.address, "pending"]), 16)
        base_fee = int(_rpc(url, "eth_getBlockByNumber", ["latest", False])["baseFeePerGas"], 16)
        try:
            tip = int(_rpc(url, "eth_maxPriorityFeePerGas", []), 16)
        except (RuntimeError, ValueError, KeyError):
            tip = 3 * GWEI // 2
        tip = max(tip, GWEI)
        max_fee = 2 * base_fee + tip
        try:
            estimate = int(_rpc(url, "eth_estimateGas", [{
                "from": account.address, "to": recipient, "value": hex(amount_wei)}]), 16)
        except RuntimeError:
            raise SendError("the transfer would fail, the recipient may reject ETH") from None
        gas = estimate * 12 // 10
        balance = int(_rpc(url, "eth_getBalance", [account.address, "latest"]), 16)
        if balance < amount_wei + gas * max_fee:
            raise SendError("the wallet has too little Sepolia ETH")
        signed = Account.sign_transaction({
            "type": 2, "chainId": SEPOLIA, "nonce": nonce, "to": recipient, "value": amount_wei,
            "gas": gas, "maxFeePerGas": max_fee, "maxPriorityFeePerGas": tip}, account.key)
        raw, tx_hash = _hex(signed.raw_transaction), _hex(signed.hash)
    except SendError:
        raise
    except ImportError:
        raise SendError("the signing library is not installed") from None
    except (OSError, ValueError, KeyError, RuntimeError, TypeError):
        raise SendError("could not reach the Sepolia network") from None

    try:
        _rpc(url, "eth_sendRawTransaction", [raw])
    except RuntimeError as e:  # the node answered and refused: nothing was broadcast
        raise SendError("the network rejected it (" + str(e)[:100] + ")") from None
    except (OSError, ValueError):  # no clear answer: it may have gone out
        raise SendError("the network did not confirm it", tx_hash=tx_hash) from None
    return tx_hash


def send_amount(to, amount_eth):
    """send_eth for a decimal ETH amount (the front end's WARDEN_TRANSFER=wallet:send_amount hook)."""
    from decimal import Decimal
    return send_eth(to, int(Decimal(str(amount_eth)) * 10**18))


def _new_wallet():
    if os.environ.get("SEPOLIA_PRIVATE_KEY"):
        print("A wallet key already exists in .env. Not making another.")
        return 1
    from eth_account import Account
    account = Account.create()
    existing = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
    fd = os.open(ENV_PATH, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        fh.write(("" if not existing or existing.endswith("\n") else "\n")
                 + f"SEPOLIA_PRIVATE_KEY={_hex(account.key)}\n")
    os.chmod(ENV_PATH, 0o600)
    print("Throwaway Sepolia wallet saved to .env. Fund this address with Sepolia test ETH:")
    print(account.address)
    return 0


def main(argv):
    load_env()
    command = argv[0] if argv else ""
    if command == "new-wallet":
        return _new_wallet()
    if command == "address":
        print(wallet_address())
        return 0
    if command == "balance":
        address = wallet_address()
        wei = int(_rpc(rpc_url(), "eth_getBalance", [address, "latest"]), 16)
        print(f"{address}: {format_eth(wei)} Sepolia ETH")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except SendError as e:
        print(f"error: {e}")
        sys.exit(1)
