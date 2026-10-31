# Warden: shared brief for all workstreams

Last updated 2026-10-30 about 19:10 PDT. This is the short version. The full plan is `PRODUCT-DEV-DOC.md`; each workstream has its own file in `tasks/`.

## Product

Warden is a firewall for crypto payments, driven over iMessage. A user texts "send 0.01 to X". The Agent asks our Auditor whether X is risky. If the verdict is HIGH, or the Auditor fails, the Agent refuses and says why. Otherwise the Agent sends a Sepolia test-ETH transfer and texts the result. The idea comes from Pyra (NexHacks 2026); everything here is rebuilt from scratch, and the Kairo API that Pyra used is dead.

Rules: never say "safe"; output is a risk signal, not a guarantee, and not a full audit. Sepolia test ether only, no real money. EVM only, no Solana.

## Event facts (Night Hack, Founders, Inc., Fort Mason, San Francisco, Friday 2026-10-30)

- Submissions due 9:00 PM. Top 7 teams demo live around 10:00 PM (90 seconds, no slides). Awards around 10:30 PM.
- Software demos cannot be localhost-only. The demo link must work on another device.
- Judges score only work done during the sprint. Disclose what existed before the event: only the Pyra idea qualifies, and no Pyra code is reused.
- Photon award, $1,000, "Best iMessage Agent You Can Text": needs a reachable iMessage number or handle in the submission. SMS-only does not qualify. Never use Akul's personal number.
- Top three prizes: $5,000 / $3,000 / $2,000 in cash plus Anthropic API credits, among other perks.

## Three workstreams

1. Auditor (Akul): `tasks/1-auditor.md`. Takes an address, returns the JSON contract. Verified-source checks, bytecode checks, scoring, a public HTTP endpoint.
2. Agent: `tasks/2-agent.md`. Parses the text request, calls the Auditor, applies the code-enforced gate, sends the Sepolia transfer, and writes the plain-English reply with Claude.
3. iMessage + UI (Photon): `tasks/3-imessage-ui.md`. The reachable iMessage handle, the inbound and outbound path, and the public web view.

## The contract everyone codes against

Schema: `schema/auditor-output.schema.json`. Examples: `fixtures/auditor-output/low.json`, `medium.json`, `high.json`.

```json
{
  "target": "0x...",
  "chainId": 11155111,
  "verdict": "LOW | MEDIUM | HIGH",
  "riskScore": 0,
  "verified": true,
  "findings": [{ "id": "tx-origin", "severity": "high | medium | low", "message": "..." }]
}
```

Field names do not change without telling every workstream. There is no "SAFE" verdict; no findings means LOW. Mock with the fixtures until the live endpoint (`GET <base-url>/screen?address=0x...&chainId=11155111`) is announced.

## Timeline (PDT)

- 19:20-19:50 Auditor bytecode checks. 19:50-20:15 Etherscan fetch and `screen()`. 20:15-20:40 public deploy.
- 20:40-20:55 freeze and end-to-end smoke test from a phone. 21:00 submission.

## Shared rules

- No keys in the repo. `.env` is gitignored. Never paste a key into chat or a commit.
- Sepolia testnet only.
- No outward posts. No public GitHub push without Akul's yes.
- Every commit ends with the Co-Authored-By line from the session's current attribution reminder.
- Report to the Conductor session on done, blocker, or needs-Akul. Silent otherwise.

## Open questions for Akul

1. `ETHERSCAN_API_KEY` for the Auditor.
2. Hosting choice for the public Auditor URL.
3. The Photon handle route (see `tasks/3-imessage-ui.md`).
4. Which sessions take the Agent and iMessage + UI workstreams.
