"""Serve local-ui/index.html with the same API as front.dashboard. Local only: 127.0.0.1, never public.

    .venv/bin/python local-ui/run.py     # http://127.0.0.1:8790, edit index.html and refresh
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from front import dashboard  # noqa: E402

dashboard.PAGE = Path(__file__).resolve().parent / "index.html"  # read on every request, so edits show on refresh
import os
dashboard.main(["--port", os.environ.get("UI_PORT", "8790"), "--host", "127.0.0.1"])
