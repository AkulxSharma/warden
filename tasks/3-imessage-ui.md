# Task 3 of 3: IMESSAGE + UI (front end and handle)

Owner: not yet assigned. Send this file to whichever session takes it. Read the shared brief too: `sessions/warden/BRIEF-workstreams.md`.

## What it is

The front end. A user texts an address, contract, or link to a Warden iMessage handle. Warden replies with the scan result. There is also a web / dashboard view that shows the same results.

## Hard rules

1. **Never use Akul's personal number in any public submission.** The handle must be a dedicated number or a dedicated Apple ID.
2. **SMS-only does not qualify for the prize.** The handle must be iMessage-capable.
3. **Sepolia testnet only** until Akul says otherwise.
4. **No outward posts.** No public GitHub push without Akul's yes.
5. **No keys in the repo.** `.env` is gitignored. Never paste keys into chat or commits.
6. **Never say "safe."** The reply is a risk signal, not a guarantee. The disclaimer comes from the Agent workstream; you display it as given.

## What you build

1. **iMessage front.**
   - Receive a message containing an address, contract, or link.
   - Parse it: detect the address, optional chain, and whether it is a link.
   - Call the Auditor for the scan, then the Agent for the reply.
   - Send the reply to the same chat.
   - Handle invalid input with a short reply asking for an address.
2. **Web / dashboard view.**
   - Paste an address, see the same verdict, score, and findings as the iMessage reply.
   - Show the disclaimer on the page.
   - Show the `verified` status clearly.
3. **Linking.** Both the iMessage front and the dashboard call the same Auditor and Agent interfaces. Do not fork the logic.

## Contracts you code against

Auditor output (fixed):

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

Agent output: a plain-English reply string (iMessage-sized) plus the disclaimer.

## Build order

1. Mock the Auditor with fixture JSON (the same shape as above). Create the LOW, MEDIUM, and HIGH fixtures.
2. Mock the Agent with a fixed reply string.
3. Build the iMessage parser and the dashboard against the mocks. Make both work end to end.
4. Swap in the real Agent and Auditor when they land. Do not change their field names to fit the UI.

## Open items (need Akul)

- Which handle to use: a dedicated number or a dedicated Apple ID. Do not assume.
- Confirm Night Hack is actually happening. Jobs notes from 10/28 say it was treated as dead.
- Confirm the real submission deadline (9 PM is unverified).
- Phantom track rules are not on disk.

## Rules

- Every commit ends with `Co-Authored-By: Claude Haiku 5.5 <noreply@anthropic.com>`.
- Report to the Conductor session (`claude-code-81`) on done, blocker, or needs-Akul.
