"""Warden web dashboard. Same pipeline as the iMessage bot.

    python3 -m front.dashboard            # http://localhost:8787

GET  /                     the page
GET  /api/status           Auditor / Agent / transfer mode, agent handle
POST /api/message {text, session}   same path as an iMessage
GET  /api/events?after=N   exchanges from every channel (live iMessage feed)
"""
import argparse
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import services
from .pipeline import handle_message, read_events

PAGE = Path(__file__).parent / "static" / "index.html"
WEB_RATE_LIMIT = 20   # messages per visitor per minute; the page is public and replies cost Claude calls
_hits = {}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/":
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif url.path == "/api/status":
            self._send(200, {"mode": services.status(),
                             "handle": os.environ.get("WARDEN_AGENT_HANDLE", "")})
        elif url.path == "/api/events":
            after = int(parse_qs(url.query).get("after", ["0"])[0])
            self._send(200, {"events": read_events(after)})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if urlparse(self.path).path != "/api/message":
            return self._send(404, {"error": "not found"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, {"error": "bad json"})
        visitor = self.headers.get("CF-Connecting-IP") or self.headers.get("X-Forwarded-For", "").split(",")[0] \
            or self.client_address[0]
        recent = [t for t in _hits.get(visitor, []) if time.time() - t < 60]
        _hits[visitor] = recent + [time.time()]
        if len(recent) >= WEB_RATE_LIMIT:
            return self._send(429, {"reply": "Too many messages. Wait a minute and try again.",
                                    "result": None, "kind": "rate_limited"})
        text = str(body.get("text", ""))[:2000]
        session = "web:" + str(body.get("session", "default"))[:64]
        self._send(200, handle_message(text, session=session, channel="web", sender="dashboard"))

    def log_message(self, *args):
        pass


def main(argv=None):
    ap = argparse.ArgumentParser(description="Warden dashboard")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8787)))
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"),
                    help="0.0.0.0 when deployed behind a public host")
    args = ap.parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[warden] dashboard on http://localhost:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
