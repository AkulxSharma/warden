# Warden front end (workstream 3: iMessage + UI)

Both fronts call `front/pipeline.py`, which calls the Auditor and Agent via `front/services.py`.
Until workstreams 1 and 2 land, those are mocks (`mock_auditor.py`, `mock_agent.py`).

## Setup

```bash
cp .env.example .env   # already done; .env is gitignored
```

Fill in `.env`:

- `WARDEN_AGENT_HANDLE`: Akul's number, the one people text. Messages on the Mac running the bot
  must be signed into that Apple ID.
- `WARDEN_TESTER_HANDLES`: testing phones (comma-separated). Always answered; not in the submission.
- `WARDEN_MODE`: `test` answers testers only. `public` also answers strangers (judges), but only
  when they send an address, a link or the word "warden", or their chat is already talking to Warden.
  Akul's normal texts get no reply either way.

## Run

```bash
python3 -m front.dashboard                       # http://localhost:8787
python3 -m front.imessage                        # uses .env
caffeinate -i python3 -m front.imessage --mode public   # judging
python3 -m unittest discover tests
```

The bot needs Full Disk Access (to read `~/Library/Messages/chat.db`) for the app it runs in,
and asks for Automation access to Messages on the first reply.

Use the venv (`.venv/bin/python`) so the Agent can reach Claude.

Demo addresses (shared fixtures in `fixtures/auditor-output/`): `0x1111…` LOW, `0x2222…` MEDIUM, `0x3333…` HIGH.

## Transfer flow (front/pipeline.py)

- `send 0.01 to 0x…` → Auditor → gate in code: HIGH or a failed check refuses; LOW/MEDIUM asks "Reply YES".
- `YES` sends the pending transfer, only for tester handles, capped by `WARDEN_MAX_SEND_ETH`, valid 5 minutes. `NO` cancels.
- Strangers (judges) and the web page get the risk check only; they can never trigger a send.
- Without `WARDEN_TRANSFER` set, YES runs in demo mode and says nothing was sent.
- A bare address is screened; anything else is a follow-up to the last scan (agent.py `answer`).

## Swapping in the real Auditor / Agent

Set in `.env` or the shell, no other change:

```
WARDEN_AUDITOR=module:audit                 # audit(address, chain_id=None, calldata=None, value=None) -> dict
WARDEN_AGENT_REPLY=module:reply             # reply(result) -> str
WARDEN_AGENT_FOLLOWUP=module:followup       # followup(result, question) -> str
```

## Judging setup (Photon award: "Best iMessage Agent You Can Text")

1. The Mac running the bot is signed into Akul's Apple ID in Messages, with Full Disk Access granted.
2. `caffeinate -i python3 -m front.imessage --mode public`, left running through judging.
3. Submission handle: Akul's number. Judges should open with an address or "warden".

Group chats are ignored and each sender is capped at 10 replies a minute.
