"""Refresh data for every registered project.

    python run_jobs.py                 # all jobs, real data
    python run_jobs.py --only market   # one job
    python run_jobs.py --demo          # synthetic data, no network needed

Schedule this once each weekday evening (cron / Task Scheduler / launchd); see README.
"""
from __future__ import annotations

import argparse
import importlib
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

LOCK_STALE_HOURS = 3

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core import env, store  # noqa: E402
from registry import JOBS  # noqa: E402

env.load()


def run_external(spec: dict, demo: bool, log) -> None:
    """Run another project's publish script with that project's own Python.

    The child gets HUB_DATA_DIR (where to write) and the hub folder on PYTHONPATH,
    so it can `from core import store` without the hub needing its dependencies.
    """
    cmd = [str(c) for c in spec["cmd"]] + (["--demo"] if demo else [])
    env = dict(os.environ, **{str(k): str(v) for k, v in spec.get("env", {}).items()})
    env["HUB_DATA_DIR"] = str(store.data_dir().resolve())
    env["PYTHONPATH"] = os.pathsep.join(p for p in (env.get("PYTHONPATH"), str(ROOT)) if p)
    env["PYTHONIOENCODING"] = "utf-8"
    # no console window per job when the hub itself runs windowless (pythonw, Task Scheduler)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(cmd, cwd=spec.get("cwd"), env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                            creationflags=flags)
    for line in proc.stdout:
        log("  " + line.rstrip())
    try:
        code = proc.wait(timeout=spec.get("timeout", 3600))
    except subprocess.TimeoutExpired:
        proc.kill()
        raise RuntimeError(f"timed out after {spec.get('timeout', 3600)}s")
    if code:
        raise RuntimeError(f"exited with code {code}")


def run_job(target, demo: bool, log) -> None:
    if isinstance(target, dict):
        run_external(target, demo, log)
    else:
        mod_name, fn_name = target.split(":")
        getattr(importlib.import_module(mod_name), fn_name)(demo=demo, log=log)


def acquire_lock(path: Path) -> bool:
    """One refresh at a time (a scheduled run and a manual one would race on the data)."""
    if path.exists() and time.time() - path.stat().st_mtime > LOCK_STALE_HOURS * 3600:
        path.unlink(missing_ok=True)  # left behind by a crashed run
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    os.write(fd, f"pid {os.getpid()} started {datetime.now():%Y-%m-%d %H:%M:%S}\n".encode())
    os.close(fd)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="*", help="run only these jobs")
    parser.add_argument("--demo", action="store_true", help="use synthetic data")
    args = parser.parse_args()

    log_dir = store.data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    lock = store.data_dir() / "jobs.lock"
    if not acquire_lock(lock):
        print(f"Another refresh is running ({lock.read_text(encoding='utf-8').strip()}). "
              f"Delete {lock} if that run is gone.")
        return 2
    try:
        return run_all(args, log_dir)
    finally:
        lock.unlink(missing_ok=True)


def run_all(args, log_dir: Path) -> int:
    log_file = (log_dir / "jobs.log").open("a", encoding="utf-8")

    def log(*parts):
        line = " ".join(str(p) for p in parts)
        print(line, flush=True)
        log_file.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {line}\n")
        log_file.flush()

    failures = 0
    for name, target in JOBS.items():
        if args.only and name not in args.only:
            continue
        log(f"=== {name} ===")
        start = time.time()
        try:
            run_job(target, args.demo, log)
            log(f"=== {name} done in {time.time() - start:.0f}s ===")
        except Exception:  # noqa: BLE001 - one failing job shouldn't stop the others
            failures += 1
            log(f"=== {name} FAILED ===\n{traceback.format_exc()}")
    log_file.close()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
