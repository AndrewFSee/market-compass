"""End-to-end check on synthetic data:  python -m pytest -q"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def demo_data(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_DATA_DIR", str(tmp_path))
    from modules.market import job
    job.run(demo=True, log=lambda *a: None)
    return tmp_path


def test_gauges_in_range(demo_data):
    from core import store
    from modules.market import config as cfg
    gauges = store.load_json("market", "gauges")
    for key, spec in cfg.GAUGES.items():
        v = gauges[key]["value"]
        assert v is not None, key
        assert spec["lo"] <= v <= spec["hi"], (key, v)
        assert gauges[key]["components"], key


def test_returns_and_breadth(demo_data):
    from core import store
    from modules.market import config as cfg
    r = store.load_frame("market", "etf_returns")
    for t in cfg.style_tickers() + list(cfg.SECTORS) + list(cfg.FACTORS):
        assert t in r.index
    b = store.load_frame("market", "breadth")
    assert b["pct_adv"].between(0, 100).all()
    assert b[["above_20", "above_50", "above_200"]].dropna().stack().between(0, 100).all()


def test_period_returns_math():
    from modules.market.indicators import period_returns
    idx = pd.bdate_range("2025-12-25", periods=30)
    s = pd.DataFrame({"X": range(100, 130)}, index=idx, dtype=float)
    r = period_returns(s, ["1D", "5D", "YTD"]).loc["X"]
    assert r["1D"] == pytest.approx((129 / 128 - 1) * 100)
    assert r["5D"] == pytest.approx((129 / 124 - 1) * 100)
    base = s.loc[s.index < "2026-01-01", "X"].iloc[-1]
    assert r["YTD"] == pytest.approx((129 / base - 1) * 100)


def test_pages_render(demo_data):
    from streamlit.testing.v1 import AppTest
    home = AppTest.from_file(str(ROOT / "views" / "home.py"), default_timeout=60).run()
    assert not home.exception
    page = AppTest.from_file(str(ROOT / "modules" / "market" / "page.py"), default_timeout=60).run()
    assert not page.exception, page.exception


def test_page_without_data(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_DATA_DIR", str(tmp_path))
    from streamlit.testing.v1 import AppTest
    page = AppTest.from_file(str(ROOT / "modules" / "market" / "page.py"), default_timeout=60).run()
    assert not page.exception
    assert page.info  # shows the "run the job first" message


def test_external_job_publishes(tmp_path, monkeypatch):
    """A {"cmd": ...} job runs in its own process and can publish through core.store."""
    monkeypatch.setenv("HUB_DATA_DIR", str(tmp_path))
    script = tmp_path / "publish.py"
    script.write_text(
        "import sys, pandas as pd\n"
        "from core import store\n"
        "print('demo' if '--demo' in sys.argv else 'real')\n"
        "store.save_frame('ext', 'table', pd.DataFrame({'x': [1.0, 2.0]}))\n",
        encoding="utf-8")
    import run_jobs
    lines = []
    run_jobs.run_job({"cmd": [sys.executable, str(script)], "cwd": str(tmp_path)}, demo=True, log=lines.append)
    assert any("demo" in line for line in lines)
    from core import store
    assert store.load_frame("ext", "table")["x"].tolist() == [1.0, 2.0]

    bad = tmp_path / "bad.py"
    bad.write_text("raise SystemExit(3)\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="code 3"):
        run_jobs.run_job({"cmd": [sys.executable, str(bad)]}, demo=False, log=lines.append)
