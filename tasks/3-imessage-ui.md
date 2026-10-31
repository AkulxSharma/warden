# Task 3 of 3: IMESSAGE + UI (the Photon track)

Owner: the iMessage teammate (handling Photon). Read `PRODUCT-DEV-DOC.md` first. Last updated 2026-10-30 about 19:10 PDT. Submissions are due at 9:00 PM. Top 7 teams demo live around 10 PM, 90 seconds each, no slides.

## What you are building

The front end of the transfer agent. A user texts the Warden handle on iMessage, for example "send 0.01 to 0xabc...". Your code hands the message to the Agent and sends the Agent's reply back. You also build a small public web view that shows the same screen result, because software demos cannot be localhost-only and the link must work on another device.

## Prize rule that drives everything

The Photon award ($1,000, "Best iMessage Agent You Can Text") needs a reachable iMessage number or handle in the submission so judges can text it. SMS-only projects do not qualify. Never use Akul's personal number; use a dedicated number or a dedicated Apple ID.

## What we verified about Photon (from photon.codes docs, 2026-10-30)

- There are two products. Stable is `spectrum-ts`; the docs say "Use Stable for production agents." Beta is "Photon 2.0", a REST API at `https://api.photon.codes/v1` with bearer keys (`pho_sk_...`) and the npm package `@photon-ai/api`. Beta iMessage supports only text and images.
- Beta gives a shared line from a pool. "Only messages from the assigned sender reach this shared-line connection," it "cannot send an unsolicited first message," and it is direct chats only (no groups). This probably does not satisfy "judges can text it," so confirm before relying on it.
- Beta inbound is polling (about every 2 seconds) or Socket.IO. Replies go through `projects.sendMessage`; delivery is not confirmed. Use the Idempotency-Key header. On a 429, stop and honor the retry guidance.
- Beta pricing: Free includes 25 shared iMessage assignments per project; Pro is $25 per month; a dedicated line is $250 per month. No per-message fees. Real money is tight, so avoid the dedicated line unless Akul approves.
- Local alternative: the open-source local kit reads `~/Library/Messages/chat.db` (polling every 2 seconds, needs Full Disk Access) and sends through AppleScript. It needs a Mac signed into the iMessage account that stays on, and Apple offers no official API, so it can be fragile.
- Not found in the docs: any Night Hack specific terms or a public-inbox option.

## Decision needed (one choice, then build)

Pick the handle route and tell the team which one: (1) Stable or the local kit on a Mac signed into a dedicated Apple ID (free, publicly textable, the Mac must stay on and online during judging); (2) a Photon dedicated line ($250 per month); (3) ask the Photon staff at the venue whether a public line exists for Night Hack, and fall back to (1) if not. Recommended default: (3) first, then (1).

## What to build

1. Inbound: receive a message and pass sender plus text to the Agent. Direct chats only.
2. Outbound: send the Agent's reply back to the same chat. Handle the confirm step: the Agent will ask "Reply YES to send," so inbound replies must reach the same pending request.
3. Web view: a public page where someone pastes an address and sees the verdict, score, findings, the `verified` status, and the disclaimer, using `GET <base-url>/screen?address=0x...&chainId=11155111`. The page must work from another device, not just localhost.
4. Show the submission handle clearly on the page.

## Contracts

Auditor output (fixed, schema at `schema/auditor-output.schema.json`, examples in `fixtures/auditor-output/`):

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

Agent output: a short plain-English reply string, iMessage-sized, that already includes the disclaimer. You display it as given and never say "safe."

## Build order

1. Mock the Agent and the Auditor with the fixtures and a fixed reply string.
2. Build the inbound and outbound path end to end with the mocks, from a real phone.
3. Build the web view against the fixtures.
4. Swap in the real Agent and the live Auditor URL when they land.
5. Test the handle and the web link from a second device before 8:45 PM.

## Rules

- No keys in the repo. `.env` is gitignored.
- Sepolia testnet only.
- No outward posts. No public GitHub push without Akul's yes.
- Every commit ends with the Co-Authored-By line from the session's current attribution reminder.
- Report to the Conductor session on done, blocker, or needs-Akul.
- Do not copy private perk or claim links from the event emails into the repo.
