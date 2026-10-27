"""Start the hub and every linked project app that isn't already running.

    python start_apps.py           # start whatever is down, in the background
    python start_apps.py --status  # show what is up
    python start_apps.py --stop    # stop them all

Apps come from LINKS entries with an "app" spec in registry.py; each runs with its own
project's venv. Output goes to data/logs/apps/<port>.log. The hub's .env (FRED_API_KEY)
is passed on, so apps that read the key from the environment get it too.
"""
from __future__ import annotations

import argparse
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core import env, store  # noqa: E402
from registry import LINKS  # noqa: E402

HUB = {"title": "Dashboard hub", "url": "http://localhost:8501",
       "app": {"cmd": [sys.executable, "-m", "streamlit", "run", "app.py", "--server.port", "8501",
                       "--server.headless", "true"], "cwd": str(ROOT)}}


def _port(url: str) -> int:
    return int(url.rsplit(":", 1)[1].split("/")[0])


def is_up(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _pids_on(port: int) -> set[int]:
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout
    return {int(m.group(1)) for m in re.finditer(rf"[\d.]+:{port}\s+\S+\s+LISTENING\s+(\d+)", out)}


def start(app: dict, port: int) -> subprocess.Popen:
    log_dir = store.data_dir() / "logs" / "apps"
    log_dir.mkdir(parents=True, exist_ok=True)
    log = (log_dir / f"{port}.log").open("a", encoding="utf-8")
    flags = 0
    if os.name == "nt":  # keep running after this script (and its console) exits, with no window
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    try:
        return subprocess.Popen(app["cmd"], cwd=app["cwd"], env=dict(os.environ), stdout=log,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                creationflags=flags | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0))
    except OSError:  # the parent's job object may not allow breakaway
        return subprocess.Popen(app["cmd"], cwd=app["cwd"], env=dict(os.environ), stdout=log,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=flags)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--status", action="store_true", help="only report what is running")
    parser.add_argument("--stop", action="store_true", help="stop the hub and all linked apps")
    args = parser.parse_args()
    env.load()
    apps = [HUB] + [link for link in LINKS if link.get("app")]

    if args.stop:
        for a in apps:
            for pid in _pids_on(_port(a["url"])):
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
                print(f"stopped {a['title']} (pid {pid})")
        return 0

    started = []
    for a in apps:
        port = _port(a["url"])
        if is_up(port):
            print(f"  up       {a['title']:32s} {a['url']}")
        elif args.status:
            print(f"  down     {a['title']:32s} {a['url']}")
        else:
            missing = [p for p in (a["app"]["cmd"][0], a["app"]["cwd"]) if not Path(p).exists()]
            if missing:
                print(f"  SKIPPED  {a['title']:32s} missing {missing[0]}")
                continue
            started.append((a, port, start(a["app"], port)))
    deadline = time.time() + 60
    for a, port, proc in started:
        while not is_up(port) and proc.poll() is None and time.time() < deadline:
            time.sleep(0.5)
        state = "started " if is_up(port) else "FAILED  "
        print(f"  {state} {a['title']:32s} {a['url']}"
              + ("" if is_up(port) else f"  (see data/logs/apps/{port}.log)"))
    return 0 if all(is_up(p) for _, p, _ in started) else 1


if __name__ == "__main__":
    sys.exit(main())
