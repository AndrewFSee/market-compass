"""Monthly rebuild of macro-regime-nowcaster's walk-forward panel (its data/features.csv).

Run by the \\MarketCompass\\MacroPanelRebuild task (scripts/register_panel_task.ps1) on the 20th,
when most of the previous month's data is out. The build refits the nowcaster once per month
since 1967 with that project's own venv (about 3 hours); the hub's macro job then republishes
it. Output goes to data/logs/macro_panel.log.

    python scripts/rebuild_macro_panel.py

Guards:
- A features.partial.csv older than a day is deleted first. Resuming it would pin the FRED
  cache from that earlier run and splice its data into the new panel.
- The previous panel is kept as features.prev.csv and put back if the new one has fewer rows
  or starts later (a build there once dropped windows silently and still reported success).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HUB = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HUB))

import pandas as pd  # noqa: E402

import registry  # noqa: E402

START = "1967-01-31"
LOG = HUB / "data" / "logs" / "macro_panel.log"
PARTIAL_MAX_AGE_HOURS = 24
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def shape(path: Path) -> tuple[int, str]:
    idx = pd.read_csv(path, index_col=0, usecols=[0]).index
    return len(idx), str(idx[0])[:10]


def main() -> int:
    macro = registry.MACRO
    python = registry.venv_python(macro)
    panel = macro / "data" / "features.csv"
    partial = panel.with_suffix(".partial.csv")
    prev = panel.with_name("features.prev.csv")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        def log(msg: str) -> None:
            fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n")
            fh.flush()

        log("=== macro panel rebuild ===")
        if not Path(python).exists():
            log(f"no venv at {python}; skipped")
            return 1
        if partial.exists() and time.time() - partial.stat().st_mtime > PARTIAL_MAX_AGE_HOURS * 3600:
            partial.unlink()
            log(f"deleted a stale {partial.name} so the build starts on fresh data")
        before = shape(panel) if panel.exists() else None
        if before:
            shutil.copy2(panel, prev)
            log(f"current panel: {before[0]} rows from {before[1]} (copy kept as {prev.name})")

        t0 = time.time()
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        rc = subprocess.run([python, "scripts/build_features.py", "--start", START, "--step", "1"],
                            cwd=macro, stdout=fh, stderr=subprocess.STDOUT, env=env,
                            creationflags=NO_WINDOW).returncode
        minutes = (time.time() - t0) / 60
        if rc != 0:
            log(f"build FAILED (exit {rc}) after {minutes:.0f} min; the previous panel is unchanged")
            return rc
        after = shape(panel)
        if before and (after[0] < before[0] or after[1] > before[1]):
            shutil.copy2(prev, panel)
            log(f"new panel ({after[0]} rows from {after[1]}) is shorter than the old one; restored it")
            return 1
        log(f"built {after[0]} rows from {after[1]} in {minutes:.0f} min")

        rc = subprocess.run([sys.executable, "run_jobs.py", "--only", "macro"], cwd=HUB, stdout=fh,
                            stderr=subprocess.STDOUT, creationflags=NO_WINDOW).returncode
        log("republished to the hub" if rc == 0 else f"hub macro job exited {rc}; the next refresh will retry")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
