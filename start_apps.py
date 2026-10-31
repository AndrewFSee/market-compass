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
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core import env  # noqa: E402
from core.apps import is_up, missing, pids_on, port_of as _port, start  # noqa: E402
from registry import LINKS  # noqa: E402

HUB = {"title": "Dashboard hub", "url": "http://localhost:8501",
       "app": {"cmd": [sys.executable, "-m", "streamlit", "run", "app.py", "--server.port", "8501",
                       "--server.headless", "true"], "cwd": str(ROOT)}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--status", action="store_true", help="only report what is running")
    parser.add_argument("--stop", action="store_true", help="stop the hub and all linked apps")
    args = parser.parse_args()
    env.load()
    apps = [HUB] + [link for link in LINKS if link.get("app")]

    if args.stop:
        for a in apps:
            for pid in pids_on(_port(a["url"])):
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
            gone = missing(a["app"])
            if gone:
                print(f"  SKIPPED  {a['title']:32s} missing {gone}")
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
