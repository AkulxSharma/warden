# Warden Agent

The Agent sits between iMessage and the chain. A teammate texts "send 0.01 to 0xabc...", the Agent asks the Auditor whether the address is risky, and then refuses or, after a YES, sends Sepolia test ETH and texts back the transaction link. It also screens a bare address and answers follow-up questions about the last result. All money is Sepolia test ether.

Everything that decides whether money moves is plain code in `transfer.py`. The language model (`agent.py`) only words the replies and cannot cause a send.

## How a message is handled

1. The sender is checked against `WARDEN_ALLOWED_SENDERS`. Anyone else gets no reply at all.
2. The text is classified as a transfer, a screen, YES, NO, a follow-up question, or something unclear.
3. For a transfer or screen, the Agent calls `GET <WARDEN_AUDITOR_URL>/screen?address=0x...&chainId=11155111`.
4. The gate decides, in code:
   - **Refuse** when the verdict is HIGH, when any finding is high severity, when the Auditor errors or times out (20 s), when the result fails `schema/auditor-output.schema.json`, or when the result is for a different address or chain.
   - **Ask for confirmation** when the verdict is LOW or MEDIUM: "Reply YES within 5 min to send, or NO to cancel."
5. YES sends exactly the pending request, once. Then the Agent replies with `https://sepolia.etherscan.io/tx/<hash>`.

Example (the bullets are written by Claude, everything else by code):

```
risk signal: MEDIUM
risk score: 30/100
- The emergency withdraw function checks who started a transaction in a weak way, so a phishing trick could let someone act as you.
- The sweep function sends funds without checking if the transfer worked, so money could fail to move while the contract acts as if it did.
Send 0.01 ETH to 0x2222...2222 on Sepolia? Reply YES within 5 min to send, or NO to cancel.
Risk signal, not a guarantee. Not a full audit.
```

## What the code guarantees

These are enforced in code and covered by tests in `tests/test_transfer.py` and `tests/test_wallet.py`.

- **Fails closed.** With no Auditor configured, nothing is sent. There is no default that guesses.
- **The model cannot send or approve.** Wording is produced after the decision. A test makes the wording say "send it now" and checks nothing is sent.
- **YES needs a pending request.** It belongs to the same sender, expires after 5 minutes, and is consumed on use, so a repeated or redelivered YES cannot send twice.
- **The newest request wins.** Any new address message, even one that is refused, clears the older pending request. A later YES can only confirm what the user saw last.
- **Amount safety.** One amount, one address, ETH only. Dollar amounts, other tokens, other chains, negative, zero and over-precise amounts are rejected. The per-transfer cap is 0.01 ETH (`WARDEN_MAX_ETH`), checked in the flow and again in the wallet.
- **Sepolia only.** The wallet asks the RPC for its chain id before every send and refuses anything but 11155111.
- **The key stays in `.env`.** It is never logged, never in an error message, never in a reply.
- **Never says "safe".** Generated text is checked for banned words, claims about risks that are not in this scan, links, addresses, and length. Anything that fails is replaced by the Auditor's own message or a fixed reply.

## Connecting the iMessage side

Python:

```python
from transfer import handle_message
reply = handle_message(sender, text)   # a string to send back, or None to stay silent
```

HTTP, for a Node front end. Start it, then POST each inbound message:

```bash
WARDEN_AGENT_TOKEN=<16+ random characters> python3 transfer.py serve
```

```bash
curl -s -X POST http://127.0.0.1:8787/message \
  -H "X-Warden-Token: $WARDEN_AGENT_TOKEN" -H "Content-Type: application/json" \
  -d '{"sender": "+14155550100", "text": "send 0.01 to 0x1111111111111111111111111111111111111111"}'
```

The response is `{"reply": "..."}`. Send that text back to the same chat. `{"reply": null}` means the sender is not allowlisted and nothing should be sent. Keep the `sender` string stable for a chat (phone number or email), because pending requests are tracked per sender. The server binds to 127.0.0.1 and refuses to start without a token, since the endpoint can trigger transfers.

## Settings

Put these in `.env` (gitignored) or the environment.

| Name | Purpose |
| --- | --- |
| `WARDEN_ALLOWED_SENDERS` | Comma-separated handles that may talk to the Agent. Empty means everyone is ignored. |
| `WARDEN_AUDITOR_URL` | Base URL of Akul's server. Setting it switches from demo data to the real Auditor. |
| `WARDEN_USE_FIXTURES` | Set to `1` for demo data when no Auditor URL exists. Only `0x1111...1111`, `0x2222...2222` and `0x3333...3333` return Akul's LOW, MEDIUM and HIGH fixtures; every other address is refused. Replies are labelled "demo data". |
| `SEPOLIA_PRIVATE_KEY` | The throwaway wallet key. `python3 wallet.py new-wallet` makes one and prints only the address. |
| `SEPOLIA_RPC_URL` | Defaults to a public Sepolia RPC. |
| `WARDEN_MAX_ETH` | Per-transfer cap, default `0.01`. |
| `ANTHROPIC_API_KEY` | For the wording. Without it every reply still works, using the Auditor's own messages. |
| `WARDEN_AGENT_MODEL` | Defaults to `claude-opus-5-5`. See the numbers below. |
| `WARDEN_AGENT_TOKEN`, `WARDEN_AGENT_HOST`, `WARDEN_AGENT_PORT` | HTTP server only. |

## Running it

```bash
uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt jsonschema
```

```bash
.venv/bin/python transfer.py chat
```

The chat command talks to the Agent as a local sender, with demo data if no Auditor is set. Run the tests with:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Live Claude tests run only when `ANTHROPIC_API_KEY` is set (`tests/test_agent_live.py`).

## The wallet

```bash
.venv/bin/python wallet.py address
```

```bash
.venv/bin/python wallet.py balance
```

Fund the printed address from any Sepolia faucet. Each transfer costs the amount plus a small fee, and the wallet refuses to send when it cannot cover both.

## Model choice, measured on real calls

For the four-finding reply (one call) and a follow-up (one call), 2026-10-30:

| Model | Reply latency | Cost per reply | Follow-up latency |
| --- | --- | --- | --- |
| `claude-opus-5-5` (default) | 5.8 to 6.6 s | $0.0070 | 2.6 s |
| `claude-sonnet-5-5` | 1.9 to 2.6 s | $0.0033 | 1.9 s |
| `claude-haiku-5-5` | 1.6 s | $0.0002 | 1.4 s |

All three passed the same guards. Set `WARDEN_AGENT_MODEL` to switch. Haiku has no server-side refusal fallback, which only matters if a request is declined.

## Known limits

- Pending requests and chat history are in memory. A restart forgets them, which fails safe: the user just asks again.
- The scan is not repeated at YES time. A request older than 5 minutes expires instead.
- The reply links the transaction right after it is broadcast and does not wait for a confirmation.
- The "never invent findings" check is a keyword map. It catches the known detector ids and common phrasing, and a paraphrase of an unlisted risk could slip through. Add a row to `RISK_TERMS` in `agent.py` when a detector id is added.
- Fixtures are demo data. Do not present them as live screening.
