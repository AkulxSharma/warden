#!/usr/bin/env python3
"""Deploy a demo contract to Sepolia from the throwaway deployer wallet, optionally verify it.

    python3 deploy.py contracts/Drainer.sol Drainer --dry-run     compile only
    python3 deploy.py contracts/Drainer.sol Drainer               deploy, print the address
    python3 deploy.py fixtures/Vulnerable.sol Vault --verify      deploy and verify on Etherscan

Needs DEPLOYER_PRIVATE_KEY (and ETHERSCAN_API_KEY for --verify) in .env. Sepolia only: refuses any
other chain id. The key is never printed. Test ether only.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests
from eth_account import Account
from web3 import Web3

import chain

ROOT = Path(__file__).resolve().parent
SEPOLIA = 11155111
COMPILER = "v0.8.20+commit.a1b79de6"
ETHERSCAN = "https://api.etherscan.io/v2/api"
TARGETS = ROOT / "demo-targets.json"


def load_env(path=ROOT / ".env"):
    env = {}
    for line in Path(path).read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


def compile_contract(path, name):
    out = subprocess.run(["solc", "--combined-json", "abi,bin", str(path)], capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"solc failed: {out.stderr.strip()[:400]}")
    contracts = json.loads(out.stdout)["contracts"]
    key = next((k for k in contracts if k.endswith(f":{name}")), None)
    if key is None:
        sys.exit(f"contract {name} not found in {path}")
    return contracts[key]["bin"], contracts[key]["abi"]


def deploy(bytecode, abi, key):
    w3 = Web3(Web3.HTTPProvider(chain.rpc_url(SEPOLIA)))
    if w3.eth.chain_id != SEPOLIA:
        sys.exit("RPC is not Sepolia, refusing to deploy")
    acct = Account.from_key(key)
    contract = w3.eth.contract(abi=abi, bytecode="0x" + bytecode)
    tx = contract.constructor().build_transaction({
        "from": acct.address, "nonce": w3.eth.get_transaction_count(acct.address),
        "chainId": SEPOLIA, "gasPrice": int(w3.eth.gas_price * 1.2)})
    cost = tx["gas"] * tx["gasPrice"] if "gas" in tx else 0
    if w3.eth.get_balance(acct.address) < cost:
        sys.exit(f"deployer {acct.address} cannot cover the deploy (needs about {cost / 1e18:.5f} ETH)")
    signed = acct.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    tx_hash = w3.eth.send_raw_transaction(raw)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if receipt.status != 1:
        sys.exit(f"deploy reverted: {tx_hash.hex()}")
    return receipt.contractAddress, tx_hash.hex()


def fund(address, amount_eth, key):
    """Send a small amount of test ETH to a deployed demo contract (plain transfer)."""
    w3 = Web3(Web3.HTTPProvider(chain.rpc_url(SEPOLIA)))
    if w3.eth.chain_id != SEPOLIA:
        sys.exit("RPC is not Sepolia, refusing to send")
    acct = Account.from_key(key)
    tx = {"to": address, "value": w3.to_wei(amount_eth, "ether"), "gas": 60000, "chainId": SEPOLIA,
          "nonce": w3.eth.get_transaction_count(acct.address), "gasPrice": int(w3.eth.gas_price * 1.2)}
    signed = acct.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    tx_hash = w3.eth.send_raw_transaction(raw)
    w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    return tx_hash.hex()


def verify(address, path, name, api_key):
    data = {"module": "contract", "action": "verifysourcecode", "contractaddress": address,
            "sourceCode": Path(path).read_text(), "codeformat": "solidity-single-file",
            "contractname": name, "compilerversion": COMPILER, "optimizationUsed": "0",
            "runs": "200", "constructorArguements": "", "apikey": api_key}
    res = requests.post(ETHERSCAN, params={"chainid": SEPOLIA}, data=data, timeout=30).json()
    if res.get("status") != "1":
        return f"verify submit failed: {str(res.get('result'))[:150]}"
    guid = res["result"]
    for _ in range(12):
        time.sleep(5)
        status = requests.get(ETHERSCAN, params={"chainid": SEPOLIA, "module": "contract",
                              "action": "checkverifystatus", "guid": guid, "apikey": api_key},
                              timeout=30).json().get("result", "")
        if "Pending" not in status:
            return status
    return "verification still pending after 60s"


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    path, name = argv[0], argv[1]
    bytecode, abi = compile_contract(path, name)
    print(f"compiled {name}: {len(bytecode) // 2} bytes")
    if "--dry-run" in argv:
        return 0
    env = load_env()
    key = os.environ.get("DEPLOYER_PRIVATE_KEY") or env["DEPLOYER_PRIVATE_KEY"]  # env var wins
    address, tx_hash = deploy(bytecode, abi, key)
    print(f"deployed {name} at {address}")
    print(f"https://sepolia.etherscan.io/address/{address}")
    if "--fund" in argv:
        amount = argv[argv.index("--fund") + 1]
        print("funded with", amount, "ETH, tx", fund(address, amount, key))
    targets = json.loads(TARGETS.read_text()) if TARGETS.exists() else []
    entry = {"name": name, "file": str(path), "address": address, "tx": tx_hash}
    if "--verify" in argv:
        entry["verification"] = verify(address, path, name, env["ETHERSCAN_API_KEY"])
        print("verification:", entry["verification"])
    targets.append(entry)
    TARGETS.write_text(json.dumps(targets, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
