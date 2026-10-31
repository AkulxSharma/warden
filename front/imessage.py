"""Warden iMessage bot. Runs on a Mac signed into the Warden Apple ID in Messages.

Reads new incoming messages from ~/Library/Messages/chat.db (read-only),
runs each through the shared pipeline, and replies in the same chat through
Messages via AppleScript.

Needs, once:
  - Full Disk Access for the app running this (Terminal, iTerm, ...), to read chat.db.
  - Automation permission for that app to control Messages (macOS asks on first send).

Usage:
  python3 -m front.imessage --allow +15551234567,you@icloud.com
  python3 -m front.imessage --any-sender      # only on a dedicated Warden Apple ID
  python3 -m front.imessage --allow <your number> --self-chat   # demo: text yourself
  python3 -m front.imessage --dry-run ...     # print replies, send nothing

Allowed senders can also come from WARDEN_ALLOWED_HANDLES (comma-separated).
"""
import argparse
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

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


def send(text, chat_guid, handle):
    for script, target in ((SEND_TO_CHAT, chat_guid), (SEND_TO_HANDLE, handle)):
        if not target:
            continue
        out = subprocess.run(["osascript", "-e", script, text, target], capture_output=True, text=True)
        if out.returncode == 0:
            return True
        print(f"[warden] send via {'chat' if script is SEND_TO_CHAT else 'handle'} failed: "
              f"{out.stderr.strip()}", file=sys.stderr)
    return False


def run(allowed, any_sender, dry_run, poll, self_chat=False):
    db = connect()
    last = db.execute("SELECT IFNULL(MAX(ROWID), 0) FROM message").fetchone()[0]
    who = "anyone" if any_sender else ", ".join(mask(h) for h in allowed)
    print(f"[warden] listening for iMessages from {who}"
          f"{' (dry run)' if dry_run else ''}. Ctrl+C to stop.")

    allowed_norm = {normalize(h) for h in allowed}
    seen, recent = set(), {}
    while True:
        rows = db.execute(NEW_MESSAGES, (last,)).fetchall()
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
            if not any_sender and normalize(handle) not in allowed_norm:
                continue
            key = (chat_guid or handle, text)
            if time.time() - recent.get(key, 0) < 15:
                continue  # self-chat can store one text as two rows
            recent[key] = time.time()

            print(f"[warden] <- {mask(handle)}: {text}")
            out = handle_message(text, session=chat_guid or handle, channel="imessage", sender=mask(handle))
            reply = REPLY_TAG + out["reply"]
            if dry_run:
                print(f"[warden] -> (dry run)\n{reply}\n")
            elif send(reply, chat_guid, handle):
                print(f"[warden] -> replied ({out['kind']})")
        time.sleep(poll)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Warden iMessage bot")
    ap.add_argument("--allow", default=os.environ.get("WARDEN_ALLOWED_HANDLES", ""),
                    help="comma-separated phone numbers or emails to answer")
    ap.add_argument("--any-sender", action="store_true",
                    help="answer anyone (only on a dedicated Warden Apple ID)")
    ap.add_argument("--self-chat", action="store_true",
                    help="also answer texts you send to an allowed handle (texting your own number)")
    ap.add_argument("--dry-run", action="store_true", help="print replies instead of sending")
    ap.add_argument("--poll", type=float, default=1.0, help="seconds between checks")
    args = ap.parse_args(argv)

    allowed = [h.strip() for h in args.allow.split(",") if h.strip()]
    if not allowed and not args.any_sender:
        sys.exit("Refusing to start without --allow or --any-sender, so the bot never "
                 "answers people who weren't part of the demo.")
    try:
        run(allowed, args.any_sender, args.dry_run, args.poll, args.self_chat)
    except KeyboardInterrupt:
        print("\n[warden] stopped")


if __name__ == "__main__":
    main()
