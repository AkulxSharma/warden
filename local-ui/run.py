"""Serve local-ui/index.html with the same API as front.dashboard. Local only: 127.0.0.1, never public.

    .venv/bin/python local-ui/run.py     # http://127.0.0.1:8790, edit index.html and refresh

UI_PORT changes the port. GET /api/wallets proxies the Auditor's /wallets (balances, transfers, blocked
attempts) from WARDEN_AUDITOR_URL, so the page can show wallet changes in near real time.
"""
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from front import dashboard  # noqa: E402

IMG_DIR = Path(__file__).resolve().parent / "img"


class Handler(dashboard.Handler):
    def do_GET(self):
        path = self.path.split("?")[0]
        if path.startswith("/img/"):   # images saved in local-ui/img, by bare file name only
            f = IMG_DIR / path[5:]
            kinds = {".png": "image/png", ".webp": "image/webp", ".jpg": "image/jpeg", ".svg": "image/svg+xml"}
            if f.parent == IMG_DIR and f.suffix in kinds and f.is_file():
                return self._send(200, f.read_bytes(), kinds[f.suffix])
            return self._send(404, {"error": "not found"})
        if path != "/api/wallets":
            return super().do_GET()
        base = os.environ.get("WARDEN_AUDITOR_URL", "").rstrip("/")
        if not base:
            return self._send(200, {"wallets": [], "transfers": [], "transfersError": "no Auditor URL configured"})
        try:
            req = urllib.request.Request(base + "/wallets", headers={"User-Agent": "warden-ui/1.0"})
            with urllib.request.urlopen(req, timeout=20) as res:
                return self._send(200, res.read(), "application/json")
        except Exception as exc:  # the panel shows the error; it never blocks the rest of the page
            return self._send(502, {"error": f"wallet data unavailable: {type(exc).__name__}"})


dashboard.Handler = Handler
dashboard.PAGE = Path(__file__).resolve().parent / "index.html"  # read on every request, so edits show on refresh
dashboard.main(["--port", os.environ.get("UI_PORT", "8790"), "--host", "127.0.0.1"])
