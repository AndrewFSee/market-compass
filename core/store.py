"""Shared storage for the hub.

Every project ("module") writes its results under ``data/<module>/`` as Parquet
(tables) or JSON (small summaries). Pages only read from here, so a slow or
broken data job never blocks the dashboard from loading.

Other projects can publish into the hub by importing this file (add the hub
folder to PYTHONPATH) or by copying it - it has no dependencies beyond pandas.
Set the HUB_DATA_DIR environment variable to point every project at the same
data folder.
"""
from __future__ import annotations

import json
import math
import os
import time
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    return Path(os.environ.get("HUB_DATA_DIR", ROOT / "data"))


def _path(module: str, name: str, ext: str) -> Path:
    return data_dir() / module / f"{name}.{ext}"


def _atomic_write(path: Path, writer) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    writer(tmp)
    # On Windows the replace fails while another process (e.g. the running hub) has the
    # target open for reading; that lasts milliseconds, so retry briefly.
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.1 * (attempt + 1))


# ----------------------------------------------------------------- tables
def save_frame(module: str, name: str, df: pd.DataFrame) -> Path:
    path = _path(module, name, "parquet")
    _atomic_write(path, lambda p: df.to_parquet(p, engine="pyarrow"))
    _record(module, name)
    return path


def load_frame(module: str, name: str) -> pd.DataFrame | None:
    path = _path(module, name, "parquet")
    return pd.read_parquet(path) if path.exists() else None


# ----------------------------------------------------------------- json
def _clean(obj):
    """Make an object JSON-safe: NaN -> None, timestamps -> ISO strings."""
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (pd.Timestamp, datetime, date)):
        return obj.isoformat()
    if hasattr(obj, "item") and not isinstance(obj, (str, bytes)):
        try:
            obj = obj.item()  # numpy scalar -> python
        except (ValueError, AttributeError):
            pass
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def save_json(module: str, name: str, obj) -> Path:
    path = _path(module, name, "json")
    text = json.dumps(_clean(obj), indent=2)
    _atomic_write(path, lambda p: p.write_text(text, encoding="utf-8"))
    _record(module, name)
    return path


def load_json(module: str, name: str):
    path = _path(module, name, "json")
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# ----------------------------------------------------------------- freshness
def stamp(module: str, name: str) -> float | None:
    """File modification time - used as a cache key by the pages."""
    for ext in ("parquet", "json"):
        p = _path(module, name, ext)
        if p.exists():
            return p.stat().st_mtime
    return None


def manifest() -> dict:
    p = data_dir() / "manifest.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _record(module: str, name: str) -> None:
    m = manifest()
    m.setdefault(module, {})[name] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    p = data_dir() / "manifest.json"
    text = json.dumps(m, indent=2, sort_keys=True)
    _atomic_write(p, lambda t: t.write_text(text, encoding="utf-8"))
