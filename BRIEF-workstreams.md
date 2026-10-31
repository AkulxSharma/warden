# Warden: workstream brief for all session members

Written 2026-10-30 (night), by the warden session. Read this before writing any code. It is the shared contract for the three workstreams.

## 0. Read first: facts that may be wrong

- **Night Hack is live (Fri 10/30).** Akul is on site. Prizes include a Photon award ($1,000, Best iMessage Agent You Can Text).
- **Submission deadline is unverified.** The "9 PM" deadline came from a relayed message, not from a sponsor page or the Night Hack site on disk. Confirm the real time and the submission form.
- **Phantom sponsor: no spec on disk.** Nothing in the repo or memory describes Phantom's track, prize, or rules. Phantom is best known as a Solana wallet. Our scope is EVM only (no Solana). If the Phantom track requires Solana, the scope conflicts and Akul must decide. Do not guess at track rules.
- **Other sponsors:** none documented on disk. Ask Akul for the full list before naming any.
- **Prize rules:** an SMS-only handle does not qualify for the Photon prize, so the iMessage handle must be a real iMessage-capable line.

## 1. Product (what Warden is)

A pre-payment risk screen. A user texts an address, contract, or link to an iMessage handle. Warden replies with:

```
risk signal: LOW | MEDIUM | HIGH
riskScore: 0-100
reasons: plain-English bullets
```

Rules:
- Never say "safe." Output is a risk signal, not a guarantee.
- It is NOT a full audit. Honest limits go in the pitch.
- Sepolia testnet only until Akul says otherwise.
- EVM only. No Solana.

## 2. Scope

**In:**
- Static source checks (we have them, see section 4).
- Audit score.
- Multi-chain for EVM only, via Etherscan v2 with the `chainid` param.
- Attack simulation on an anvil fork (`eth_call` plus balance diff). About half a day of work.
- Fix suggestions written as text by Claude. Never auto-edit code.
- Bytecode checks for UNVERIFIED addresses: EIP-7702 delegation prefix `0xef0100`, EIP-1967 proxy slots, DELEGATECALL / SELFDESTRUCT / ORIGIN opcodes (skip PUSH data), owner-only selectors such as `upgradeTo`, `mint`, `pause`, `blacklist`.

**Out for this build:** ML trained on exploits, mutation testing, auto-generated tests, auto-fix, Solana, PDF report (later), CI/CD action (later).

**Not Kairo.** Kairo (the commercial auditor Pyra used) is dead. Do not call its API. Do not depend on Slither at runtime. Pyra (badri1i/Pyra, MIT) is reference only; we build from scratch.

## 3. The contract (all three workstreams code against this)

The Auditor (workstream 1) emits exactly this shape:

```json
{
  "target": "0x...",
  "chainId": 1,
  "verdict": "LOW | MEDIUM | HIGH",
  "riskScore": 0,
  "verified": true,
  "findings": [
    { "id": "reentrancy", "severity": "high", "message": "..." }
  ]
}
```

- `verdict` is derived from `riskScore`. The thresholds are set by the Auditor and documented in its code.
- Input to the Auditor: address, optional `chainId`, optional calldata and value.
- Do not change field names without telling every workstream.

## 4. Workstreams

### Workstream 1: AUDITOR (owner: Akul)

Analysis Core. Builds:
- Bytecode detectors (section 2 list).
- Verified-source path. Reuse the logic in `warden_scan.py`.
- Fork simulation on anvil.
- Scoring, which produces `riskScore` and `verdict`.

Test requirement: unit test every detector against fixtures:
- a clean contract (`fixtures/Safe.sol` is the clean fixture),
- a known-bad contract (`fixtures/Vulnerable.sol`),
- an EOA,
- an EIP-7702 delegation on local anvil.

Current on-disk state (per Akul's note, not independently re-verified by the warden session):
- `warden_scan.py` is committed (`b5e1491`). It is a solc-AST detector covering reentrancy (state write after external call), unprotected state write, arbitrary send, `tx.origin`, unchecked low-level call, and selfdestruct / delegatecall.
- It matches Slither High/Medium on `fixtures/Vulnerable.sol`, and `fixtures/Safe.sol` comes back CLEAN.
- `fixtures/` is untracked. `.gitignore` has an uncommitted change.
- Tooling: `.venv` with slither and solc-select; solc 0.8.20.

### Workstream 2: AGENT (owner: TBD, not assigned)

Takes the Auditor JSON and writes the plain-English explanation with Claude. Handles follow-up questions.

Rules:
- Never invent findings that are not in the JSON.
- Owns the prompt, the wording, and the disclaimer: "risk signal, not a guarantee."
- Never says "safe."

Start: mock the Auditor with fixture JSON until workstream 1 lands. Use the section 3 shape.

### Workstream 3: IMESSAGE + UI (owner: TBD, not assigned)

- iMessage front: a reachable handle, a dedicated number or Apple ID. NEVER Akul's personal number in any public submission. SMS-only does not qualify for the prize.
- Web / dashboard view.
- Links workstreams 1 and 2.

Start: mock the Agent and the Auditor with fixture JSON until they land.

## 5. Shared rules (every workstream)

- No keys in the repo. `.env` is gitignored. Never commit `.env` or paste keys in chat.
- Sepolia testnet only until Akul says otherwise.
- No outward posts.
- No public GitHub push without Akul's yes.
- Every commit ends with: `Co-Authored-By: Claude Haiku 5.5 <noreply@anthropic.com>`
- Alert the Conductor session (`claude-code-81`) on done, blocker, or needs-Akul. Silent otherwise.

## 6. Open questions for Akul (block the build)

2. Confirm the real submission deadline and form.
3. Phantom track rules, and whether Solana is required.
4. Full sponsor list.
5. Which handle goes on iMessage (dedicated number or Apple ID).
