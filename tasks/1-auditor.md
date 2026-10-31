# Task 1 of 3: AUDITOR (Analysis Core)

Owner: Akul. This file tells the other two workstreams exactly what the Auditor will give them and when. Read `PRODUCT-DEV-DOC.md` for the full plan. Last updated 2026-10-30 about 19:10 PDT. Submissions are due at 9:00 PM.

## What the product is now

Warden is a firewall for crypto payments, driven over iMessage. A user texts "send 0.01 to X". The Agent asks the Auditor whether X is risky. If the Auditor says HIGH, or fails, the Agent refuses. Otherwise the Agent sends a Sepolia test-ETH transfer and texts the result. The Auditor is the risk check at the center. It is a risk signal, not an audit, and it never says "safe."

## What you can rely on right now

- The output contract, as a JSON Schema: `schema/auditor-output.schema.json`.
- Three example outputs for mocking: `fixtures/auditor-output/low.json`, `medium.json`, `high.json`. All three validate against the schema.
- `auditor.py` has `analyze_source(path)` working on the verified-source path (4 of 4 unit tests pass in `tests/test_auditor.py`).

## Output contract (fixed)

```json
{
  "target": "0x...",
  "chainId": 11155111,
  "verdict": "LOW | MEDIUM | HIGH",
  "riskScore": 0,
  "verified": true,
  "findings": [
    { "id": "tx-origin", "severity": "high | medium | low", "message": "..." }
  ]
}
```

Field names do not change without telling the Agent and iMessage + UI workstreams. There is no "SAFE" or "CLEAN" verdict. No findings means LOW.

## Interface other workstreams will call (coming, not live yet)

`GET <base-url>/screen?address=0x...&chainId=11155111` returns the JSON above. `GET <base-url>/health` returns a simple OK. Until the public base URL exists, mock with the three fixtures. Akul will announce the URL. Treat any non-200 response, a timeout, or JSON that fails the schema as an Auditor failure, which the Agent must handle as "refuse."

## What the Auditor checks

Verified source (Etherscan v2 with the `chainid` parameter), using our own detectors in `warden_scan.py`: `reentrancy-state-after-call`, `unprotected-state-write`, `arbitrary-send`, `tx-origin`, `unchecked-low-level-call`, `dangerous-selfdestruct`, `delegatecall`.

Unverified addresses (bytecode only): `eoa` (no code), `eip7702-delegation` (code starts with `0xef0100`), `eip1967-proxy` (implementation, admin, or beacon slot set), `unverified-source`, `delegatecall-opcode`, `selfdestruct-opcode`, `origin-opcode`, and `admin-selectors` (owner-only functions such as upgradeTo, mint, pause, blacklist).

Optional if time allows: attack simulation on an anvil fork (`sim-revert`, `sim-drains-sender`).

Scoring (provisional): 50 per high finding, 15 per medium, 5 per low, capped at 100. The verdict is the worst severity found.

## Timeline

- 19:20-19:50: bytecode checks and unit tests.
- 19:50-20:15: Etherscan fetch and the `screen()` entry point.
- 20:15-20:40: HTTP server and public deploy.
- 20:40-20:55: freeze and end-to-end smoke test.
- Fork simulation only if ahead of schedule.

## Out of scope

ML trained on exploits, mutation testing, auto-generated tests, auto-fix, Solana, PDF report, CI/CD action. Do not call Kairo (dead). Do not depend on Slither at runtime.

## Rules

- No keys in the repo. `.env` is gitignored.
- Sepolia testnet only.
- No outward posts. No public GitHub push without Akul's yes.
- Every commit ends with the Co-Authored-By line from the session's current attribution reminder.
- Report to the Conductor session on done, blocker, or needs-Akul.

## Open items needing Akul

- `ETHERSCAN_API_KEY` in `.env`.
- Hosting choice for the public URL.
- The history squash and public flip of the repo.
