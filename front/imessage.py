"""Warden iMessage bot. Runs on a Mac whose Messages is signed into the agent
handle (WARDEN_AGENT_HANDLE in .env).

Reads new incoming messages from ~/Library/Messages/chat.db (read-only),
runs each through the shared pipeline, and replies in the same chat through
Messages via AppleScript.

Needs, once:
  - Full Disk Access for the app running this (Terminal, iTerm, ...), to read chat.db.
  - Automation permission for that app to control Messages (macOS asks on first send).

Settings come from .env (see .env.example):
  WARDEN_AGENT_HANDLE     the number people text (shown in logs, masked)
  WARDEN_TESTER_HANDLES   testing phones, always answered
  WARDEN_MODE             test: testers only
                          public: also strangers, but only for Warden-looking
                          texts (address, link, "warden") or chats already
                          talking to Warden, so the owner's normal texts are ignored

Usage:
  python3 -m front.imessage                   # uses .env
  caffeinate -i python3 -m front.imessage --mode public   # judging
  python3 -m front.imessage --dry-run         # print replies, send nothing
"""
import argparse
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import aliases

from . import config
from .parse import parse
from .pipeline import handle_message

CHAT_DB = Path.home() / "Library" / "Messages" / "chat.db"
REPLY_TAG = "🛡 Warden\n"   # marks our own replies so a self-chat never loops

NEW_MESSAGES = """
SELECT m.ROWID, m.text, m.attributedBody, m.is_from_me, h.id, c.guid, c.style
FROM message m
LEFT JOIN handle h ON h.ROWID = m.handle_id
LEFT JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
LEFT JOIN chat c ON c.ROWID = cmj.chat_id
WHERE m.ROWID > ?
ORDER BY m.ROWID
"""
GROUP_CHAT_STYLE = 43
RATE_LIMIT = 10   # replies per sender per minute

# Warden stays silent in a chat until someone texts "Hey Warden", and goes silent again on "End Warden".
ACTIVATION = re.compile(r"^\s*hey[\s,!.]+warden\b[\s,.!:;-]*", re.I)
END = re.compile(r"^\s*(end|stop|bye)\s+warden\b", re.I)
CHAT_IDLE_SECONDS = 1800   # a chat that has been quiet this long needs "Hey Warden" again
GOODBYE = "Warden session ended. Text \"Hey Warden\" to start again."

# One-line description of each predefined demo name, shown in the first reply.
ROLES = {
    "akul.eth": "a normal receiving address",
    "andrew.eth": "the agent's own wallet",
    "drainer.eth": "a contract that can self-destruct",
    "vault.eth": "a verified vault with several bugs",
    "rugpull.eth": "a token whose owner can mint and blacklist",
    "proxy.eth": "an upgradeable proxy",
    "phisher.eth": "a wallet that trusts tx.origin",
}


def greeting():
    """First reply after "Hey Warden": what Warden does and every predefined name to try."""
    names = "\n".join(f"- {name}: {ROLES[name]}" if name in ROLES else f"- {name}" for name in aliases.ALIASES)
    return ("Warden here. I check an address before you pay it.\n\n"
            f"Predefined wallets you can try:\n{names}\n\n"
            "Text e.g. \"send 0.001 to akul.eth\", or paste any 0x address to screen it. "
            "Text \"End Warden\" when you're done.\n"
            "Sepolia testnet only. Risk signal, not a guarantee.")


def decide(text, chat_key, open_chats, now):
    """What to do with a text given the chats Warden is active in.

    Returns (action, body): ("ignore", None) stay silent, ("greet", None) Warden was just activated,
    ("end", None) the user ended the session, ("handle", text) pass text to the pipeline.
    Mutates open_chats (chat key -> time of last activity).
    """
    last = open_chats.get(chat_key)
    active = last is not None and now - last <= CHAT_IDLE_SECONDS
    if END.match(text):
        open_chats.pop(chat_key, None)
        return ("end", None) if active else ("ignore", None)
    match = ACTIVATION.match(text)
    if match:
        open_chats[chat_key] = now
        rest = text[match.end():].strip()
        return ("handle", rest) if rest else ("greet", None)
    if active:
        open_chats[chat_key] = now
        return ("handle", text)
    return ("ignore", None)

SEND_TO_CHAT = """
on run argv
  tell application "Messages" to send (item 1 of argv) to chat id (item 2 of argv)
end run
"""
SEND_TO_HANDLE = """
on run argv
  tell application "Messages"
    set svc to 1st account whose service type = iMessage
    send (item 1 of argv) to participant (item 2 of argv) of svc
  end tell
end run
"""


def decode_attributed_body(blob):
    """Pull the plain string out of an NSAttributedString typedstream.

    Recent macOS often leaves message.text NULL and stores the body here.
    """
    if not blob or b"NSString" not in blob:
        return None
    body = blob.split(b"NSString", 1)[1][5:]
    if body[:1] == b"\x81":
        length, start = int.from_bytes(body[1:3], "little"), 3
    elif body[:1] == b"\x82":
        length, start = int.from_bytes(body[1:4], "little"), 4
    else:
        length, start = body[0], 1
    return body[start:start + length].decode("utf-8", errors="replace")


def mask(handle):
    """Never show a full number or email on screen or in logs."""
    if not handle:
        return "unknown"
    if "@" in handle:
        name, _, domain = handle.partition("@")
        return f"{name[:2]}…@{domain}"
    return f"…{handle[-4:]}"


def normalize(handle):
    handle = (handle or "").strip().lower()
    return handle if "@" in handle else "".join(ch for ch in handle if ch.isdigit())[-10:]


def connect():
    try:
        db = sqlite3.connect(f"file:{CHAT_DB}?mode=ro", uri=True)
        db.execute("SELECT 1 FROM message LIMIT 1")
        return db
    except sqlite3.Error as exc:
        sys.exit(f"Can't read {CHAT_DB} ({exc}).\n"
                 "Grant Full Disk Access to the app running this command:\n"
                 "System Settings > Privacy & Security > Full Disk Access, then restart that app.")


def send(text, chat_guid, handle, attempts=3):
    """Send text, trying the chat then the handle, and retry so a busy or closed Messages app
    does not drop a reply."""
    for attempt in range(attempts):
        for script, target in ((SEND_TO_CHAT, chat_guid), (SEND_TO_HANDLE, handle)):
            if not target:
                continue
            out = subprocess.run(["osascript", "-e", script, text, target], capture_output=True, text=True)
            if out.returncode == 0:
                return True
            print(f"[warden] send via {'chat' if script is SEND_TO_CHAT else 'handle'} failed: "
                  f"{out.stderr.strip()}", file=sys.stderr)
        if attempt < attempts - 1:
            subprocess.run(["open", "-g", "-a", "Messages"], capture_output=True)  # make sure Messages is running
            time.sleep(1 + attempt)
    return False


def wants_warden(text):
    """Would a stranger's text be meant for Warden? Used in public mode."""
    return parse(text).kind in {"scan", "transfer", "tx_hash", "ens", "link_no_address"} or "warden" in text.lower()


def run(allowed, public, dry_run, poll, self_chat=False, agent_handle=""):
    db = connect()
    last = db.execute("SELECT IFNULL(MAX(ROWID), 0) FROM message").fetchone()[0]
    who = ", ".join(mask(h) for h in allowed) or "no testers"
    if public:
        who += " + anyone, but only in chats that started with 'Hey Warden'"
    print(f"[warden] agent handle {mask(agent_handle) if agent_handle else '(WARDEN_AGENT_HANDLE not set)'}")
    print(f"[warden] answering {who}"
          f"{' (dry run)' if dry_run else ''}. Ctrl+C to stop.")

    allowed_norm = {normalize(h) for h in allowed}
    seen, recent, per_sender, open_chats = set(), {}, {}, {}
    while True:
        try:
            rows = db.execute(NEW_MESSAGES, (last,)).fetchall()
        except sqlite3.Error as exc:  # Messages briefly locks chat.db: wait, reconnect, never die
            print(f"[warden] chat.db read failed ({exc}); retrying", file=sys.stderr)
            time.sleep(max(poll, 1.0))
            try:
                db = connect()
            except SystemExit:
                pass
            continue
        for rowid, text, body, from_me, handle, chat_guid, style in rows:
            last = max(last, rowid)
            if rowid in seen:
                continue
            seen.add(rowid)
            text = text or decode_attributed_body(body)
            if not text or text.startswith(REPLY_TAG.strip()):
                continue
            if from_me and not self_chat:
                continue  # our own outgoing messages
            if style == GROUP_CHAT_STYLE:
                continue
            chat_key = chat_guid or handle
            if normalize(handle) not in allowed_norm and not public:
                continue
            key = (chat_guid or handle, text)
            if time.time() - recent.get(key, 0) < 15:
                continue  # self-chat can store one text as two rows
            recent[key] = time.time()
            stamps = [t for t in per_sender.get(handle, []) if time.time() - t < 60]
            per_sender[handle] = stamps + [time.time()]
            if len(stamps) >= RATE_LIMIT:
                continue  # public handle: ignore floods instead of replying to each

            action, body = decide(text, chat_key, open_chats, time.time())
            if action == "ignore":
                continue  # Warden was not activated in this chat: stay silent
            print(f"[warden] <- {mask(handle)}: {text}")
            if action in ("greet", "end"):
                reply = REPLY_TAG + (greeting() if action == "greet" else GOODBYE)
                if dry_run:
                    print(f"[warden] -> (dry run)\n{reply}\n")
                elif send(reply, chat_guid, handle):
                    print(f"[warden] -> replied ({action})")
                else:
                    print(f"[warden] reply to {mask(handle)} could not be sent ({action})", file=sys.stderr)
                continue
            text = body
            try:
                out = handle_message(text, session=chat_key, channel="imessage", sender=mask(handle),
                                     can_transfer=True)  # anyone who started the chat with "Hey Warden"
            except Exception as exc:  # one bad message must not take the handle down
                print(f"[warden] error on message {rowid}: {exc!r}", file=sys.stderr)
                continue
            reply = REPLY_TAG + out["reply"]
            if dry_run:
                print(f"[warden] -> (dry run)\n{reply}\n")
            elif send(reply, chat_guid, handle):
                print(f"[warden] -> replied ({out['kind']})")
            else:
                print(f"[warden] reply to {mask(handle)} could not be sent ({out['kind']})", file=sys.stderr)
        time.sleep(poll)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Warden iMessage bot")
    ap.add_argument("--allow", default=",".join(config.handles("WARDEN_TESTER_HANDLES")),
                    help="comma-separated tester numbers or emails (default: WARDEN_TESTER_HANDLES)")
    ap.add_argument("--mode", choices=("test", "public"), default=os.environ.get("WARDEN_MODE", "test") or "test",
                    help="test: testers only; public: also strangers sending Warden-looking texts")
    ap.add_argument("--self-chat", action="store_true",
                    help="also answer texts you send to an allowed handle (texting your own number)")
    ap.add_argument("--dry-run", action="store_true", help="print replies instead of sending")
    ap.add_argument("--poll", type=float, default=1.0, help="seconds between checks")
    args = ap.parse_args(argv)

    allowed = [h.strip() for h in args.allow.split(",") if h.strip()]
    if not allowed and args.mode == "test":
        sys.exit("No testers set. Put your number in WARDEN_TESTER_HANDLES in .env "
                 "(or pass --allow), or run with --mode public.")
    try:
        run(allowed, args.mode == "public", args.dry_run, args.poll, args.self_chat,
            os.environ.get("WARDEN_AGENT_HANDLE", ""))
    except KeyboardInterrupt:
        print("\n[warden] stopped")


if __name__ == "__main__":
    main()
