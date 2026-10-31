# Prompt for Abdullah's Claude: connect the transfer agent to the live Auditor and prove it end to end

Paste this whole file into your Claude session and follow it step by step. Do not commit this file; it contains a temporary URL.

## Where things stand (do not redo any of this)

- You built the transfer agent on `agent-workstream`: `transfer.py` (intent parser, code gate, YES confirmation, `http_auditor`), `wallet.py` (Sepolia wallet, `new-wallet`), `agent.py` (wording), tests, `AGENT.md`. Keep every guarantee in `AGENT.md`.
- Everything is now merged into `main` (commit `24ba222`): your branch, Andrew's iMessage bot and dashboard (`front/`, his PR #1, now merged), and Akul's Auditor (`auditor.py`, `bytecode.py`, `chain.py`, `etherscan.py`, `server.py`, `Dockerfile`). Run `git pull origin main` and work from `main`. Both open PRs (#1 Andrew, #2 yours) now show MERGED because their commits are in `main`, and neither branch has newer commits than `main`, so start new work from `main` (not from `agent-workstream`) to avoid diverging. The combined suite passes: 164 tests, 6 skipped. As of 19:33 PDT `front/` still does not call `transfer.py`, so Step 2 below is still open.
- The Auditor is live. Akul checked your client against it: `transfer.http_auditor` plus `transfer.check_scan` and `transfer.gate` handle the real responses correctly (EOA gives LOW and the gate says confirm; a contract we cannot compile gives MEDIUM and confirm; a bad address returns HTTP 400 and your client raises, so the agent refuses). You did not need to know how the Auditor works internally; the contract and schema are enough, and your validation is stricter than ours.

Submissions are due at 9:00 PM PDT today. Prefer finishing the end-to-end run over polishing.

## Step 1: point the Agent at the live Auditor

The Auditor runs on Akul's Mac behind ngrok at this temporary URL:

```
https://2b1a-12-125-194-54.ngrok-free.app
```

Put it in `.env` (gitignored):

```
WARDEN_AUDITOR_URL=https://2b1a-12-125-194-54.ngrok-free.app
```

Check it before touching code:

```bash
curl -s -A "warden-agent/1.0" "$WARDEN_AUDITOR_URL/health"
curl -s -A "warden-agent/1.0" "$WARDEN_AUDITOR_URL/screen?address=0x000000000000000000000000000000000000dEaD"
```

Expected: `{"ok": true}`, then JSON with `"verdict": "LOW"` and `"riskScore": 5`.

**Known problem on a python.org Python for macOS:** `urllib` fails with `CERTIFICATE_VERIFY_FAILED` against an https URL, because that Python ships without root certificates. Akul's Mac hit exactly this. Fix it once, either way:

- Run the `Install Certificates.command` that comes with the python.org install (in `/Applications/Python 3.x/`), or
- Set `SSL_CERT_FILE` to certifi's bundle: `pip install certifi` then `export SSL_CERT_FILE="$(python3 -m certifi)"`. Put the export in whatever script starts the agent and the iMessage bot.

If this is not fixed, the Auditor call fails and the agent refuses every request, which is the safe behavior but a useless demo. Do not turn off certificate verification.

Things to know about the URL:
- It changes if ngrok restarts. If calls start failing, ask Akul for the current URL. Do not guess.
- Akul's Mac must stay awake and online. If the Auditor is down, refusing is correct. Do not add a fallback that guesses a verdict.

New finding ids from the Auditor: `source-not-scanned`, `unverified-source`, `eoa`, `eip7702-delegation`, `eip1967-proxy`, `delegatecall-opcode`, `selfdestruct-opcode`, `origin-opcode`, `admin-selectors`. Confirm each has a row in `RISK_TERMS` in `agent.py` so the "never invent findings" check does not flag honest wording about it.

## Step 2: fix the duplicated gate (the most important change)

Andrew's `front/pipeline.py` contains its own gate and its own pending-YES logic. It is weaker than yours: it refuses only on `verdict == "HIGH"`, it does not refuse on a high-severity finding inside a non-HIGH verdict, and it does not check that the result is for the address and chain that were asked about. His `WARDEN_TRANSFER=module:function` hook is where a real send plugs in, so wiring your wallet to it would put real sends behind the weaker gate.

Do one of these with Andrew, before any send is connected to the iMessage bot:
- Preferred: have `front` hand tester messages to `transfer.handle_message(sender, text)` so there is exactly one gate, one pending-request store, and one wallet path, or
- At minimum: make `front/pipeline.py` call `transfer.check_scan` and `transfer.gate`, and send only through `wallet.py`.

Keep Andrew's rule that judges and the web page can never trigger a send; only allowlisted tester handles can.

## Step 3: known test targets (verified live)

| Target | Address | Auditor result |
| --- | --- | --- |
| LOW | `0x000000000000000000000000000000000000dEaD` (an EOA) | LOW, score 5, finding `eoa` |
| MEDIUM | `0x7b79995e5f793A07Bc00c21412e50Ecae098E7f9` (a Sepolia contract our compiler cannot build) | MEDIUM, score 15, finding `source-not-scanned` |
| HIGH | not available yet | An address whose bytecode contains SELFDESTRUCT, or an EOA with an EIP-7702 delegation. Ask Akul, or see Step 5. |

LOW and MEDIUM both ask for YES and then send; MEDIUM is not a refusal. For a demo that does not burn funds, send to your own second throwaway address, not the dead address.

## Step 4: the test wallet and funding

All money is Sepolia test ether. Never use a wallet that has ever held real funds. Never buy ETH for this.

1. Create the agent wallet with your tool: `.venv/bin/python wallet.py new-wallet` (saves `SEPOLIA_PRIVATE_KEY` to `.env`, prints only the address). Never print, log, commit, or message the key.
2. Create a recipient address (no key needed to receive): `.venv/bin/python -c "from eth_account import Account; print(Account.create().address)"`.
3. Fund the agent wallet with free Sepolia ETH. About 0.05 ETH is plenty (cap is 0.01 per transfer plus a small fee). Faucet rules change and sources disagree, so read each faucet's own page:
   - Alchemy Sepolia faucet: https://www.alchemy.com/faucets/ethereum-sepolia (reported as 0.1 ETH per 24 hours; some pages say a small mainnet balance is required)
   - Google Cloud Web3 Sepolia faucet (may check for a small mainnet balance)
   - GetBlock, QuickNode, and Chainstack also run Sepolia faucets (account or balance rules vary)
   A brand-new wallet can fail "hold mainnet ETH" checks. Faucets pay any address, so a teammate whose normal wallet passes can request test ETH and forward it. Test ETH has no value.
4. Check with `.venv/bin/python wallet.py balance`. Do not run end-to-end sends until it is above 0.02 ETH.

**Test chain:** use the public Sepolia testnet for the demo and for judging. Judges can open every transaction on https://sepolia.etherscan.io, and the live Auditor reads Sepolia. Your wallet already refuses any chain that is not 11155111. A local anvil fork of Sepolia is optional and only useful for fast local tests of the wallet and gate; Foundry is not installed on Akul's Mac, and the hosted Auditor cannot see a local fork. If you use one, check that `eth_chainId` returns `0xaa36a7` first.

## Step 5: prove it end to end, in order

1. With `WARDEN_AUDITOR_URL` set and certificates fixed, run `.venv/bin/python transfer.py chat` as an allowlisted sender and send `screen 0x7b79995e5f793A07Bc00c21412e50Ecae098E7f9`. Expect a MEDIUM reply that mentions bytecode-only checks, and no "safe".
2. Send `send 0.001 to <your recipient address>`. The recipient is an EOA, so the Auditor returns LOW and the agent asks for YES. Reply YES. Confirm a real transaction hash comes back, and open it on sepolia.etherscan.io.
3. Refusal path A: set `WARDEN_AUDITOR_URL` to a wrong URL for one run. The agent must refuse and say the check could not run. Restore it.
4. Refusal path B (a HIGH target): ask Akul for one, or deploy a tiny contract containing `selfdestruct` from the agent wallet and screen its address. Unverified, so the Auditor flags `selfdestruct-opcode` (high) and `unverified-source` (medium), the verdict is HIGH, and the agent must refuse. Spend at most 10 minutes on this; if slow, tell Akul and he will supply a HIGH address.
5. Run `.venv/bin/python -m unittest discover -s tests -v` and confirm everything passes.

## Step 6: connect iMessage and report

Andrew's iMessage bot is `front/imessage.py` (it reads `~/Library/Messages/chat.db` on the handle Mac and replies through Messages). Akul's phone is the agent handle and a teammate's phone is the allowlisted sender. Put the allowlisted sender handles in `.env` only (`WARDEN_ALLOWED_SENDERS` for your agent, `WARDEN_TESTER_HANDLES` for `front`). Never put phone numbers in the repo. Whichever process answers texts must use the single gate from Step 2.

When the end-to-end run passes, or when you hit a blocker or need Akul, message the Conductor session with one to three lines: what happened, the key fact (a tx hash, a verdict, an error), and what you need.

## Step 7: aliases instead of long addresses (only after Steps 1-5 pass)

Akul wants to text `send 0.01 to akul.eth` instead of a 0x address. Build a local alias book first. It is code-controlled and safe. Do not build real ENS lookups unless Akul asks.

- The two aliases for the demo: `akul.eth` is the receiver, and `andrew.eth` is the sender (the teammate who texts the agent). Map each to a public Sepolia test address. The agent spends from its own single wallet (`SEPOLIA_PRIVATE_KEY`). For the demo story, make that funded wallet the one labelled `andrew.eth`, and make `akul.eth` a separate recipient address. Per-user wallets with separate keys are out of scope tonight.
- Put the book in a small module (for example `aliases.py`). Public addresses are fine in code. Phone numbers and keys never go in code or the repo.
- Resolve the alias in the intent parser, before the Auditor call. The Auditor still receives only the resolved 0x address; its contract does not change.
- The confirmation must show both the alias and the short address, for example `akul.eth -> 0xab...12`. YES sends to the resolved address.
- Match aliases case-insensitively and exactly otherwise, with no fuzzy matching. An unknown alias gets "I don't know that name" and the Auditor is not called.
- Aliases change only in code or config, never by a text. A message like `alias akul.eth = 0x...` must do nothing.
- Chain: Ethereum on Sepolia only. If someone asks for BTC or another chain, reply that Warden handles Ethereum on Sepolia only. Bitcoin is not EVM and is out of scope.
- Tests: a known alias resolves and the Auditor is called with the 0x address; an unknown alias refuses without calling the Auditor; an alias-setting text changes nothing; the confirmation contains both the alias and the short address; BTC is rejected.
- Tell Andrew: `front` says ENS names are not supported. It should use the same resolver so alias handling lives in one place.

## Rules that never change

- No keys in the repo. `.env` is gitignored. Never paste a key into chat or a commit.
- Sepolia test ether only. No real money, ever.
- Never say "safe." The reply is a risk signal, not a guarantee, and not a full audit.
- The language model never decides whether money moves. Code does.
- No outward posts. No public GitHub push without Akul's yes.
- Every commit ends with the Co-Authored-By line from your session's current attribution reminder.
