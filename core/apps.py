"""Start and check the linked project apps (LINKS entries in registry.py with an "app" spec).

Used by start_apps.py and by the hub's launch page, so a sidebar link can start its app."""
from __future__ import annotations

import os
import re
import socket
import subprocess
from pathlib import Path

from core import store


def port_of(url: str) -> int:
    return int(url.rsplit(":", 1)[1].split("/")[0])


def launch_url(url: str) -> str:
    """Hub link that starts the app at `url` if it isn't running, then opens it (views/launch.py)."""
    return f"/launch?app={port_of(url)}"


def is_up(port: int, timeout: float = 0.5) -> bool:
    # Windows retries a refused loopback connection, so a down port always costs the full timeout
    with socket.socket() as s:
        s.settimeout(timeout)
        return s.connect_ex(("127.0.0.1", port)) == 0


def pids_on(port: int) -> set[int]:
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout
    return {int(m.group(1)) for m in re.finditer(rf"[\d.]+:{port}\s+\S+\s+LISTENING\s+(\d+)", out)}


def missing(app: dict) -> str | None:
    """The venv python or project folder that doesn't exist, if any."""
    return next((p for p in (app["cmd"][0], app["cwd"]) if not Path(p).exists()), None)


def log_path(port: int) -> Path:
    return store.data_dir() / "logs" / "apps" / f"{port}.log"


def start(app: dict, port: int) -> subprocess.Popen:
    """Start an app detached (it outlives the caller), output appended to its log."""
    path = log_path(port)
    path.parent.mkdir(parents=True, exist_ok=True)
    log = path.open("a", encoding="utf-8")
    flags = 0
    if os.name == "nt":  # keep running after the caller (and its console) exits, with no window
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    try:
        return subprocess.Popen(app["cmd"], cwd=app["cwd"], env=dict(os.environ), stdout=log,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                creationflags=flags | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0))
    except OSError:  # the parent's job object may not allow breakaway
        return subprocess.Popen(app["cmd"], cwd=app["cwd"], env=dict(os.environ), stdout=log,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=flags)
