#!/usr/bin/env python3
"""Warden Auditor HTTP server. Stdlib only.

    GET /health                               -> {"ok": true}
    GET /screen?address=0x..&chainId=11155111 -> Auditor JSON (schema/auditor-output.schema.json)

Errors return {"error": "..."} with a non-200 status. The Agent must treat any non-200, timeout,
or schema-invalid body as 'refuse'. Env: ETHERSCAN_API_KEY, PORT (default 8000), RPC_URL_<chainId>.

The URL is public, so /screen is rate limited per client and successful results are cached for a
few seconds to protect the Etherscan key and the RPC. Failures are never cached.
"""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import auditor
import chain
import wallets

try:
    import jsonschema
except ImportError:
    jsonschema = None

SCHEMA_PATH = Path(__file__).resolve().parent / "schema" / "auditor-output.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text()) if SCHEMA_PATH.exists() else None

_ROOT = Path(__file__).resolve().parent
_NEW_UI = _ROOT / "front" / "static" / "index.html"   # the redesigned page with the progress tracker
PAGE = Path(os.environ["WARDEN_PAGE"]) if os.environ.get("WARDEN_PAGE") else (
    _NEW_UI if _NEW_UI.exists() else _ROOT / "dashboard.html")
AGENT_URL = os.environ.get("WARDEN_AGENT_URL", "http://127.0.0.1:8787")  # front.dashboard, the chat backend
WALLET_TTL = 4      # seconds the wallet snapshot is reused (the page polls every 5)
CACHE_TTL = 30      # seconds a successful result is reused for the same (address, chainId)
RATE_LIMIT = 60     # /screen requests per client per minute
_cache = {}         # (address, chain_id) -> (expires_at, result)
_hits = {}          # client -> request timestamps in the last minute
_lock = threading.Lock()


def reset():
    """Clear the cache and rate-limit state (used by tests)."""
    with _lock:
        _cache.clear()
        _hits.clear()


def _rate_limited(client, now):
    with _lock:
        recent = [t for t in _hits.get(client, []) if now - t < 60]
        recent.append(now)
        _hits[client] = recent
        return len(recent) > RATE_LIMIT


def handle(raw_path, client="local", now=None):
    """Return (status, body dict) for a GET request path."""
    now = time.time() if now is None else now
    url = urlparse(raw_path)
    if url.path == "/health":
        return 200, {"ok": True}
    if url.path == "/wallets":
        if _rate_limited(client, now):
            return 429, {"error": "rate limited, retry in a minute"}
        with _lock:
            hit = _cache.get("wallets")
        if hit and hit[0] > now:
            return 200, hit[1]
        try:
            snap = wallets.snapshot()
        except (chain.ChainError, OSError, ValueError) as exc:
            return 502, {"error": f"wallet data unavailable: {exc}"}
        with _lock:
            _cache["wallets"] = (now + WALLET_TTL, snap)
        return 200, snap
    if url.path != "/screen":
        return 404, {"error": "not found"}

    query = parse_qs(url.query)
    address = (query.get("address") or [""])[0]
    try:
        chain_id = int((query.get("chainId") or [auditor.DEFAULT_CHAIN_ID])[0])
    except ValueError:
        return 400, {"error": "invalid chainId"}
    if not auditor.ADDRESS_RE.match(address):
        return 400, {"error": "invalid address"}
    if _rate_limited(client, now):
        return 429, {"error": "rate limited, retry in a minute"}

    key = (address, chain_id)  # exact address string: the result echoes it back as 'target'
    with _lock:
        hit = _cache.get(key)
    if hit and hit[0] > now:
        return 200, hit[1]

    try:
        result = auditor.screen(address, chain_id)
    except auditor.AuditorError as exc:
        return 502, {"error": str(exc)}
    if jsonschema and SCHEMA:
        try:
            jsonschema.validate(result, SCHEMA)
        except jsonschema.ValidationError:
            return 500, {"error": "auditor produced invalid output"}
    with _lock:
        _cache[key] = (now + CACHE_TTL, result)
    return 200, result


class Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        # CORS preflight, so a page on another origin (e.g. Vercel) can call the API with the
        # ngrok-skip-browser-warning header
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "ngrok-skip-browser-warning, content-type")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_POST(self):
        """Forward the in-page chat to the local agent (front.dashboard). Web chat never sends money."""
        if urlparse(self.path).path != "/api/message":
            return self._json(404, {"error": "not found"})
        length = min(int(self.headers.get("Content-Length") or 0), 4096)
        body = self.rfile.read(length)
        forwarded = self.headers.get("X-Forwarded-For", "").split(",")[0].strip() or self.client_address[0]
        if _rate_limited("chat:" + forwarded, time.time()):
            return self._json(429, {"reply": "Too many messages. Wait a minute and try again.",
                                    "result": None, "kind": "rate_limited"})
        req = urllib.request.Request(AGENT_URL + "/api/message", data=body, method="POST",
                                     headers={"Content-Type": "application/json", "X-Forwarded-For": forwarded})
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                payload, status = res.read(), res.status
        except (urllib.error.URLError, OSError):
            return self._json(502, {"reply": "The agent is offline right now. Try again in a minute.",
                                    "result": None, "kind": "agent_offline"})
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if urlparse(self.path).path == "/api/events":
            # live feed for the progress tracker; /api/status is deliberately NOT proxied (it shows the agent handle)
            query = urlparse(self.path).query
            try:
                with urllib.request.urlopen(f"{AGENT_URL}/api/events?{query}", timeout=10) as res:
                    payload, status = res.read(), res.status
            except (urllib.error.URLError, OSError):
                return self._json(502, {"error": "agent offline", "events": []})
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(payload)
            return
        if urlparse(self.path).path in ("/", "/dashboard") and PAGE.exists():
            data = PAGE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
            return
        forwarded = self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        status, body = handle(self.path, client=forwarded or self.client_address[0])
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):  # one line per request, no query string (addresses only)
        sys.stderr.write("%s %s\n" % (self.command, urlparse(self.path).path))


def main():
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"warden auditor listening on :{port}", file=sys.stderr)
    server.serve_forever()


if __name__ == "__main__":
    main()
