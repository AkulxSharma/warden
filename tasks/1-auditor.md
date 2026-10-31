# Task 1 of 3: AUDITOR (Analysis Core)

Owner: Akul. This file is for reference by the other sessions so they know what the Auditor will produce. Read the shared brief too: `sessions/warden/BRIEF-workstreams.md`.

## What it is

The Auditor is the analysis core of Warden. Given an EVM address, it returns a risk verdict, a 0-100 score, and a list of findings. It is a pre-payment risk screen, not a full audit. It must never be described as "safe."

## Input

- `address` (required): the target contract or EOA.
- `chainId` (optional): defaults to Sepolia for now (testnet only until Akul says otherwise).
- `calldata` and `value` (optional): used for the fork simulation.

## Output (fixed contract)

```json
{
  "target": "0x...",
  "chainId": 11155111,
  "verdict": "LOW | MEDIUM | HIGH",
  "riskScore": 0,
  "verified": true,
  "findings": [
    { "id": "reentrancy", "severity": "high", "message": "..." }
  ]
}
```

Rules for this contract:
- Field names do not change without telling the Agent and iMessage+UI workstreams.
- `verdict` is derived from `riskScore`. The thresholds are set in the Auditor code and documented there.
- Every finding in `findings` has an `id`, a `severity`, and a plain `message`. The Agent may only explain findings that appear in this list.
- `verified` is `true` when source is fetched and checked, `false` when the address is bytecode-only.

## Components

1. **Verified-source path.** Fetch verified source through Etherscan v2 using the `chainid` parameter. Run the static detectors. Reuse the logic in `warden_scan.py` (committed in `b5e1491`). It is a solc-AST detector covering reentrancy, unprotected state write, arbitrary send, `tx.origin`, unchecked low-level call, and selfdestruct / delegatecall. It matches Slither High/Medium on `fixtures/Vulnerable.sol`, and `fixtures/Safe.sol` comes back clean.
2. **Bytecode path for UNVERIFIED addresses.** Check for:
   - EIP-7702 delegation prefix `0xef0100`,
   - EIP-1967 proxy storage slots,
   - DELEGATECALL, SELFDESTRUCT, and ORIGIN opcodes (skip PUSH data when scanning),
   - owner-only selectors such as `upgradeTo`, `mint`, `pause`, `blacklist`.
3. **Fork simulation.** Run `eth_call` on a local anvil fork and compute a balance diff. About half a day of work.
4. **Scoring.** Combine findings into `riskScore` and `verdict`.

## Tests (required)

Unit test every detector against fixtures:
- clean contract: `fixtures/Safe.sol`
- known-bad contract: `fixtures/Vulnerable.sol`
- an EOA
- an EIP-7702 delegation, on local anvil

## Out of scope for this build

ML trained on exploits, mutation testing, auto-generated tests, auto-fix, Solana, PDF report, CI/CD action. Do not call Kairo's API (it is dead). Do not depend on Slither at runtime. Pyra (badri1i/Pyra, MIT) is reference only.

## Current state on disk

- `warden_scan.py` committed. `fixtures/` untracked. `.gitignore` has an uncommitted change.
- `.venv` exists with slither and solc-select. solc 0.8.20.

## Rules

- No keys in the repo. `.env` is gitignored.
- Sepolia testnet only.
- No outward posts. No public GitHub push without Akul's yes.
- Every commit ends with `Co-Authored-By: Claude Haiku 5.5 <noreply@anthropic.com>`.
- Report to the Conductor session (`claude-code-81`) on done, blocker, or needs-Akul.

## Blockers

- Night Hack status conflicts (Akul says we are at it; jobs notes from 10/28 say it is dead). Confirm first.
- Submission deadline (9 PM) is unverified.
- Phantom track rules are not on disk. Phantom is a Solana wallet, which conflicts with EVM only. Akul decides.
