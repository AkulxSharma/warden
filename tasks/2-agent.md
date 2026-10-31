# Task 2 of 3: AGENT (plain-English explanation)

Owner: not yet assigned. Send this file to whichever session takes it. Read the shared brief too: `sessions/warden/BRIEF-workstreams.md`.

## What it is

The Agent takes the Auditor's JSON output and writes the plain-English reply that the user sees. It also answers follow-up questions about the same scan. It uses Claude to write the text.

## Input

The Auditor output, exactly as defined below. You do not call the Auditor directly in your own code path except through the interface Akul provides. Until the Auditor lands, use fixture JSON.

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

## Output

A short iMessage-sized reply (a few short bullets, not an essay) containing:
- the verdict as `risk signal: LOW | MEDIUM | HIGH`,
- the `riskScore` (0-100),
- plain-English reasons, one per finding,
- the disclaimer.

Follow-up questions ("what does reentrancy mean?", "is this token a scam?") get a direct answer, but only from the JSON in this scan.

## Hard rules

1. **Never invent findings.** Every reason in the reply must map to an entry in `findings`. If the user asks about a risk that is not in the JSON, say the scan did not flag it. Do not claim it is absent.
2. **Never say "safe."** Not in the reply, not in a follow-up.
3. **Always include the disclaimer:** this is a risk signal, not a guarantee, and it is not a full audit.
4. **Honest limits:** say when a contract is unverified and the scan used bytecode checks only.
5. Do not change field names in the JSON.

## What you own

- The prompt that drives the Claude call.
- The wording and tone of the reply.
- The disclaimer text.
- The follow-up handling (a single scan's context, nothing else).

## Build order

1. Write the prompt and the reply format against the fixture JSON.
2. Create at least three fixtures: a LOW result, a MEDIUM result with a verified contract, and a HIGH result for an unverified address with a delegation finding.
3. Test that the reply uses only findings present in each fixture. Add a check that fails if the reply mentions a finding id that is absent from the JSON.
4. Test follow-up questions against the same fixtures.
5. Swap the fixture for the real Auditor output when workstream 1 lands. Do not change the prompt to make the real output fit.

## Rules

- No keys in the repo. `.env` is gitignored.
- Sepolia testnet only.
- No outward posts. No public GitHub push without Akul's yes.
- Every commit ends with `Co-Authored-By: Claude Haiku 5.5 <noreply@anthropic.com>`.
- Report to the Conductor session (`claude-code-81`) on done, blocker, or needs-Akul.

## Blockers

- Night Hack status and the submission deadline are unconfirmed. Ask Akul before any deadline-driven choice.
- Phantom track rules are not on disk. Do not assume Solana support is needed or not needed.
