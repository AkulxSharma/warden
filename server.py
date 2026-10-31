#!/usr/bin/env python3
"""Warden Auditor HTTP server. Stdlib only.

    GET /health                               -> {"ok": true}
    GET /screen?address=0x..&chainId=11155111 -> Auditor JSON (schema/auditor-output.schema.json)

Errors return {"error": "..."} with a non-200 status. The Agent must treat any non-200, timeout,
or schema-invalid body as 'refuse'. Env: ETHERSCAN_API_KEY, PORT (default 8000), RPC_URL_<chainId>.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import auditor

try:
    import jsonschema
except ImportError:
    jsonschema = None

SCHEMA_PATH = Path(__file__).resolve().parent / "schema" / "auditor-output.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text()) if SCHEMA_PATH.exists() else None


def handle(raw_path):
    """Return (status, body dict) for a GET request path."""
    url = urlparse(raw_path)
    if url.path == "/health":
        return 200, {"ok": True}
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

    try:
        result = auditor.screen(address, chain_id)
    except auditor.AuditorError as exc:
        return 502, {"error": str(exc)}
    if jsonschema and SCHEMA:
        try:
            jsonschema.validate(result, SCHEMA)
        except jsonschema.ValidationError:
            return 500, {"error": "auditor produced invalid output"}
    return 200, result


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        status, body = handle(self.path)
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
