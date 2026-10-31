# Task 2 of 3: AGENT (the transfer agent and the plain-English voice)

Owner: not yet assigned. Send this file to whichever session takes it. Read `PRODUCT-DEV-DOC.md` first. Last updated 2026-10-30 about 19:10 PDT. Submissions are due at 9:00 PM.

## What you are building

The Agent is the brain between iMessage and the chain. A user texts "send 0.01 to 0xabc...". You parse the request, ask the Auditor whether the target is risky, and either refuse or send a Sepolia test-ETH transfer. Then you text back what happened. This is the Pyra idea (a firewall between the ask and the transaction) rebuilt from scratch. Do not copy Pyra's code.

All money is Sepolia test ether. Nothing real is spent.

## The flow

1. Receive a message from the iMessage workstream (sender handle plus text).
2. Check the sender against an allowlist of the team's own handles. Ignore everyone else silently.
3. Work out the intent: a transfer request (address plus amount), a screen-only request (just an address), a confirmation ("YES"), or a follow-up question about the last result.
4. For a transfer or screen request, call the Auditor: `GET <base-url>/screen?address=0x...&chainId=11155111`. Until the base URL exists, use the fixtures in `fixtures/auditor-output/` (`low.json`, `medium.json`, `high.json`).
5. Apply the gate in code, not in a prompt:
   - verdict HIGH: refuse and explain.
   - Auditor error, timeout, non-200, or JSON that fails `schema/auditor-output.schema.json`: refuse and say the check could not run.
   - verdict LOW or MEDIUM: show the result and ask "Reply YES to send." Send only after a YES from the same sender for the same pending request.
6. Send the transfer on Sepolia from a throwaway test wallet. The private key lives in `.env` only and is never committed, logged, or sent in a message. A small per-transfer cap (about 0.01 ETH) is recommended.
7. Text back the result: sent (with `https://sepolia.etherscan.io/tx/<hash>`), refused (with reasons), or failed.

The language model never decides whether to send. The gate is plain code.

## Auditor JSON you will receive

```json
{
  "target": "0x...",
  "chainId": 11155111,
  "verdict": "LOW | MEDIUM | HIGH",
  "riskScore": 0,
  "verified": true,
  "findings": [{ "id": "tx-origin", "severity": "medium", "message": "..." }]
}
```

## Wording rules (you own the prompt and the disclaimer)

- Never invent findings. Every reason must map to an entry in `findings`. If asked about something not in the JSON, say the scan did not flag it; do not claim it is absent.
- Never say "safe." Say it is a risk signal, not a guarantee, and not a full audit.
- If `verified` is false, say the check used bytecode only and is less complete.
- Replies are short, iMessage-sized, a few bullets. Lead with the verdict and score.
- A follow-up question is answered only from the JSON of the scan being discussed.

## Build order

1. Intent parser plus allowlist plus pending-request state (one pending request per sender).
2. The gate function, with unit tests: HIGH refuses, Auditor error refuses, timeout refuses, bad JSON refuses, LOW or MEDIUM asks for YES, YES sends, no YES means no send.
3. Wording prompt, tested against the three fixtures, with a check that fails if a reply mentions a finding id absent from the JSON.
4. Sepolia sender (viem, ethers, or web3.py) with the throwaway wallet, tested on Sepolia with a small amount.
5. Swap the fixtures for the live Auditor URL when Akul announces it. Do not change the prompt to fit the live output.

## Rules

- No keys in the repo. `.env` is gitignored. Never paste a key into chat or a commit.
- Sepolia testnet only.
- No outward posts. No public GitHub push without Akul's yes.
- Every commit ends with the Co-Authored-By line from the session's current attribution reminder.
- Report to the Conductor session on done, blocker, or needs-Akul.
- Disclose in the submission that the Pyra idea existed before the event; no Pyra code is reused.
