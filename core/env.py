"""Load KEY=value lines from the hub's .env into os.environ (real env vars win).

Keeps secrets such as FRED_API_KEY out of the code. External jobs inherit them.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(path: Path | None = None) -> None:
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.removeprefix("export ").strip()
        os.environ.setdefault(key, value.strip().strip("'\""))
