# Warden front end (workstream 3: iMessage + UI)

Both fronts call `front/pipeline.py`, which calls the Auditor and Agent via `front/services.py`.
Until workstreams 1 and 2 land, those are mocks (`mock_auditor.py`, `mock_agent.py`).

## Run

```bash
python3 -m front.dashboard                 # http://localhost:8787
python3 -m front.imessage --allow +15551234567            # answer texts from that number
python3 -m front.imessage --allow +15551234567 --self-chat  # demo by texting your own number
python3 -m unittest discover tests
```

The bot needs Full Disk Access (to read `~/Library/Messages/chat.db`) for the app it runs in,
and asks for Automation access to Messages on the first reply. It refuses to start without
`--allow` or `--any-sender`, so it never answers people outside the demo.

Demo addresses: `0x1000…0001` LOW, `0x2000…0002` MEDIUM, `0x7702…0003` HIGH (unverified, 7702).

## Swapping in the real Auditor / Agent

Set in `.env` or the shell, no other change:

```
WARDEN_AUDITOR=module:audit                 # audit(address, chain_id=None, calldata=None, value=None) -> dict
WARDEN_AGENT_REPLY=module:reply             # reply(result) -> str
WARDEN_AGENT_FOLLOWUP=module:followup       # followup(result, question) -> str
```

## Judging setup (Photon award: "Best iMessage Agent You Can Text")

Judges text the handle from their own phones, so during judging the bot must answer anyone:

1. Sign Messages on the demo Mac into a **dedicated Warden Apple ID** (never a personal number in the
   submission; SMS-only does not qualify). Confirm it shows as iMessage (blue), not SMS.
2. Grant Full Disk Access to the terminal app, then run and leave it running:
   `caffeinate -i python3 -m front.imessage --any-sender`
3. Put that Apple ID (email or number) in the submission as the reachable handle.

`--any-sender` is only safe on the dedicated account: on a personal account it would reply to everyone.
Group chats are ignored and each sender is capped at 10 replies a minute.
