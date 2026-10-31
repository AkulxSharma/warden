# Dashboard progress tracker: spec for the UI teammate

Written 2026-10-30 evening. Akul is improving the Auditor; one teammate is improving the UI. This file is what the UI teammate (and their Claude) should build. Read `PRODUCT-DEV-DOC.md` first for the whole system.

## Goal

When someone texts the Warden agent on iMessage, the dashboard shows the request moving through the flow as a live progress bar, without the page ever reloading. The page only asks the server for updates once per second and redraws what changed.

## The progress steps

1. **SMS received.** The agent receives the text. The progress bar starts.
2. **Checking for vulnerabilities.** The Auditor is screening the target address.
3. **Awaiting confirmation.** The check passed and the agent asked the sender to reply YES.
4. **Payment done.** The transfer was sent on Sepolia. Show the amount, who paid whom (aliases such as `andrew.eth` and `akul.eth`), and a link to the transaction on https://sepolia.etherscan.io.
5. **Reset and show.** After a short pause (about 20 seconds) the tracker returns to its idle state ("Ready, text the agent to start") and the wallet balances refresh to show the result. The page itself does not reload.

Two end states the five steps do not cover, and the tracker must handle both:
- **Refused.** The Auditor said HIGH, or the check could not run. The bar stops at step 2 in a clear refusal state and shows the reasons the agent gave. It then resets like step 5. This is the `drainer.eth` demo.
- **Cancelled or expired.** The sender said NO, or the five-minute YES window ran out. Show it, then reset.

## Live updates without refreshing

- Poll the events endpoint once per second with `fetch`, passing a cursor (the last event index seen) so each poll returns only new events. The existing `front/dashboard.py` already serves `GET /api/events?after=N`.
- Do not reload the page or rebuild the whole DOM each tick. Update only the parts that changed.
- Pause polling while the browser tab is hidden and resume when it is visible again.
- If a poll fails, keep showing the last state and show a small "Reconnecting" note. Do not clear the screen.

## The data the tracker needs (this part is not built yet)

Today `front/pipeline.py` writes one event after a whole exchange is finished (sender, text, reply, kind, result). That is too late to show steps 1 to 3 live. The pipeline must also write a stage event at each step. Suggested event shape, one JSON line each in the existing events log:

```json
{ "ts": 0, "convo": "<stable id for the chat>", "stage": "received",
  "target": "akul.eth", "amountEth": "0.001" }
```

`stage` is one of: `received`, `screening`, `awaiting_confirmation`, `paid`, `refused`, `cancelled`, `expired`, `failed`. Add `verdict`, `riskScore`, and `reasons` on `screening` results and `refused`, and add `txHash` on `paid`. Emit `received` as soon as a message is accepted (before the Auditor call), `screening` when the Auditor call starts and finishes, `awaiting_confirmation` when the pending request is created, and `paid` after the transfer is broadcast. Stage names are a contract; do not rename them without telling the pipeline owner.

Files involved: `front/pipeline.py` (emit the events), `front/dashboard.py` (serve them), `front/static/index.html` (render them). Keep `transfer.py` as the single gate. The UI must never decide whether money moves.

## The wallet panel

Show the main wallet (the agent wallet, `andrew.eth`) and the other wallet (the receiver, `akul.eth`) with live balances, plus `drainer.eth` as a small "vulnerable test target" card. Balances come from `GET /wallets` on the Auditor server (or the same data from any read-only Sepolia source). After a payment, the balances must visibly change when the tracker resets. `dashboard.html` and `wallets.py` in the repo are a working reference; reuse their layout and data shape if helpful.

## Privacy and safety

- Never show a full phone number or email. Show the masked handle the pipeline already provides.
- Show short addresses (first six and last four characters) and aliases, not raw message text beyond what the stage needs.
- Never show or log a private key.
- Build every dynamic string with `textContent`, never `innerHTML`.
- Test ether on Sepolia only. State clearly on the page that it has no real value.

## Hosting

The page must work from a public URL on another device, not just localhost. Note one real constraint: the iMessage events live on the Mac that runs the bot. A page hosted on Vercel can only show them if it calls a public API that reaches that Mac (the existing public tunnel), and that API must allow cross-origin requests. The simplest reliable setup for tonight is to serve the page from the same Mac behind the tunnel. If you also want a Vercel copy, make it a static page that reads the tunnel's API and shows "Reconnecting" cleanly when the Mac is unreachable.

## Making the UI deployable on Vercel (do this from the start)

Akul will put the finished UI on Vercel as a static site that talks to the Mac over the public tunnel. So:

- Every network call goes through one base URL: `var API = (window.WARDEN_API || "").replace(/\/$/, "");`, then `fetch(API + "/wallets")`, `fetch(API + "/api/events?after=" + n)`, `fetch(API + "/api/message", ...)`. When `WARDEN_API` is not set the base is empty and the page works same-origin, as it does when served from the Mac. A deploy step injects `window.WARDEN_API`; do not hard-code any URL.
- When `API` is not empty, send the header `ngrok-skip-browser-warning: 1` on every request, or the free tunnel returns an interstitial page instead of JSON. The server already answers the CORS preflight for GET and POST with that header.
- Use one self-contained file (inline CSS and JS) or plain static files, with no build step and no server-side code.
- The API the page may rely on: `GET /wallets`, `GET /api/events?after=N`, `POST /api/message` with `{text, session}`, and `GET /screen?address=0x...`. Reference implementation: `dashboard.html`. Do not call `/api/status`; it is not exposed because it shows the agent handle.

## How to know it works

1. A scripted run with `handle_message` for a send to `akul.eth` produces the stages in order (`received`, `screening`, `awaiting_confirmation`) and, after YES, `paid` with a transaction hash.
2. A send to `drainer.eth` produces `received`, `screening`, then `refused` with the reasons.
3. Feed saved example events to the page and check each stage renders, including refused, cancelled, and expired.
4. Check that the page does not reload (the tab's scroll position and text selection survive an update) and that polling is about once per second.
5. Check a phone-width layout and reduced-motion preference.
6. All existing tests still pass (`python3 -m unittest discover -s tests`).

## Rules

- Work lands on `main`, after tests pass. No force pushes.
- No keys, tokens, or phone numbers in the repo. `.env` is gitignored.
- Every commit ends with the Co-Authored-By line from your session's current attribution reminder.
- Report to the Conductor session when the tracker works end to end, or when you are blocked.
