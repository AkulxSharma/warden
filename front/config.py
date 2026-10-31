"""Load .env from the repo root into os.environ (no dependency).

Values already set in the shell win over .env. See .env.example for the keys.
"""
import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_env(path=ENV_FILE):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def handles(var):
    return [h.strip() for h in os.environ.get(var, "").split(",") if h.strip()]


load_env()
