#!/usr/bin/env python3
"""Build the static Vercel site from Abdullah's local-ui page.

    python3 make-site.py <local-ui dir> <output dir> <API base URL> [handle to show]

Differences from the local page: every network call goes to the API base (the permanent tunnel domain)
with the ngrok skip-warning header; the web chat box is removed (the Screen form stays); the wallet
panel reads GET /wallets, which lists every wallet; images use relative paths; and /api/status is not
called, because it exposes the agent's phone number. The handle badge appears only if a handle is passed.
"""
import json
import pathlib
import re
import shutil
import sys


def swap(text, old, new, count=1):
    if old not in text:
        sys.exit(f"make-site: expected text not found: {old[:70]!r}")
    return text.replace(old, new, count)


def main(src_dir, out_dir, api, handle=""):
    src, out = pathlib.Path(src_dir), pathlib.Path(out_dir)
    h = (src / "index.html").read_text(encoding="utf-8")

    # config for the page
    h = swap(h, "<head>", "<head>\n<script>window.WARDEN_API = %s; window.WARDEN_HANDLE = %s;</script>"
             % (json.dumps(api), json.dumps(handle)))
    # the whole live iMessage feed box sits in the right-hand column and stays in view while scrolling
    h = swap(h, "</style>", "  aside .panel { position: sticky; top: 24px; }\n"
             "  aside .feed { max-height: calc(100vh - 150px); }\n</style>")
    # the input hint: how to try it over iMessage (or a name when no handle was given)
    hint = (f"Paste an address, or text “Hey Warden” to {handle} on iMessage" if handle
            else "Paste an address or a name like vault.eth")
    h = swap(h, 'placeholder="0x address or explorer link"', f'placeholder="{hint}"')
    # demo buttons: only ones that work (they screen a name), labelled with what Warden really returns
    demos = [("LOW", "akul.eth"), ("MEDIUM", "rugpull.eth"), ("MEDIUM", "proxy.eth"),
             ("MEDIUM", "phisher.eth"), ("HIGH", "vault.eth"), ("HIGH", "drainer.eth")]
    buttons = "".join(f'\n        <button data-addr="{name}">{level} ({name})</button>' for level, name in demos)
    h, n = re.subn(r'<div class="demos">.*?</div>', f'<div class="demos">Try:{buttons}\n      </div>', h, count=1, flags=re.S)
    if n != 1:
        sys.exit("make-site: demo buttons block not found")
    # images: relative so they work from any host
    h = h.replace('href="/img/icon.png"', 'href="img/icon.png"')
    h = h.replace('src="/img/icon.png"', 'src="img/icon.png"')
    h = h.replace('src="/img/hero.png"', 'src="img/hero.png"')
    # layout: keep two columns. The chat panel (phone with the message thread and input) is removed, and
    # the Live iMessage feed box moves from the left column into the right-hand column in its place.
    feed_re = r'\n    <section class="panel">\n      <h2 class="label">Live iMessage feed</h2>.*?</section>\n'
    m = re.search(feed_re, h, flags=re.S)
    if not m:
        sys.exit("make-site: live feed section not found")
    feed = m.group(0).strip("\n")
    h = h.replace(m.group(0), "\n", 1)
    h, n = re.subn(r"\n  <aside>.*?</aside>", lambda _: "\n  <aside>\n" + feed + "\n  </aside>", h, count=1, flags=re.S)
    if n != 1:
        sys.exit("make-site: aside not found")
    if "chatForm" in h.split("<script>", 1)[0]:
        sys.exit("make-site: chat panel markup still present")

    # API base and headers
    h = swap(h, "const session = Math.random().toString(36).slice(2);",
             "const session = Math.random().toString(36).slice(2);\n"
             "const API = (window.WARDEN_API || \"\").replace(/\\/$/, \"\");\n"
             "const NGROK = API ? {\"ngrok-skip-browser-warning\": \"1\"} : {};\n"
             "const HANDLE = window.WARDEN_HANDLE || \"\";")
    h = swap(h, 'const res = await fetch("/api/message", {\n    method: "POST", headers: {"Content-Type": "application/json"},',
             'const res = await fetch(API + "/api/message", {\n    method: "POST", headers: {"Content-Type": "application/json", ...NGROK},')
    h = swap(h, 'await fetch("/api/wallets")', 'await fetch(API + "/wallets", {headers: NGROK})')
    h = swap(h, 'await fetch("/api/events?after=" + after)', 'await fetch(API + "/api/events?after=" + after, {headers: NGROK})')

    # the screen form still works; the chat thread does not exist any more
    new_chat = '''/* ---- screen ---- */
let busy = false;
async function chat(text) {
  if (busy) return;
  busy = true; $("scanBtn").disabled = true;
  chainScanning();
  const started = performance.now();
  try {
    const out = await send(text);
    const wait = Math.max(0, 900 - (performance.now() - started)); // let the scan read as a scan
    await new Promise((r) => setTimeout(r, reduced ? 0 : wait));
    if (out.result) { chainDone(out.result); renderResult(out.result, out.reply, "from the web page (the web never sends money)", out.kind); }
    else { chainIdle(); const r = $("result"); r.className = "panel result empty"; r.textContent = out.reply || "Send an address to screen."; }
  } catch (e) {
    chainIdle(); const r = $("result"); r.className = "panel result empty"; r.textContent = "Could not reach the server. Try again.";
  } finally {
    busy = false; $("scanBtn").disabled = false;
  }
}

'''
    h, n = re.subn(r"/\* ---- chat ---- \*/.*?(?=\$\(\"chatForm\"\))", lambda m: new_chat, h, count=1, flags=re.S)
    if n != 1:
        sys.exit("make-site: chat block not found")
    h, n = re.subn(r"\$\(\"chatForm\"\)\.addEventListener\(\"submit\".*?\n\}\);\n", "", h, count=1, flags=re.S)
    if n != 1:
        sys.exit("make-site: chatForm handler not found")

    # status: do not call /api/status (it carries the phone number); show a handle only if one was given
    h, n = re.subn(r"fetch\(\"/api/status\"\).*?\n\}\);\npoll\(\);",
                   'if (HANDLE) { $("handleBadge").textContent = "Text Warden: " + HANDLE; $("handleBadge").hidden = false; }\npoll();',
                   h, count=1, flags=re.S)
    if n != 1:
        sys.exit("make-site: status block not found")

    for gone in ('fetch("/api/', 'fetch("/api/status', '$("thread")', '$("chatForm")', 'chatInput'):
        if gone in h:
            sys.exit(f"make-site: leftover reference {gone!r}")

    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(h, encoding="utf-8")
    if (src / "img").is_dir():
        shutil.copytree(src / "img", out / "img", dirs_exist_ok=True)
    (out / "vercel.json").write_text('{ "cleanUrls": true }\n', encoding="utf-8")
    print(f"built {out / 'index.html'} ({len(h)} bytes)")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(2)
    main(*sys.argv[1:5])
