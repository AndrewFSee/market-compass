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


def test_project_folder_resolution(tmp_path, monkeypatch):
    import registry
    monkeypatch.setattr(registry, "PROJECTS", tmp_path)
    (tmp_path / "flat").mkdir()
    (tmp_path / "cloned" / "cloned" / ".git").mkdir(parents=True)  # cloned into a same-name folder
    (tmp_path / "pkg" / ".git").mkdir(parents=True)  # repo whose package shares its name
    (tmp_path / "pkg" / "pkg").mkdir()
    assert registry.project("flat") == tmp_path / "flat"
    assert registry.project("cloned") == tmp_path / "cloned" / "cloned"
    assert registry.project("pkg") == tmp_path / "pkg"


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


def _fake_credit(tmp_path, monkeypatch):
    """Minimal tables in the schema credit-spread-analyzer's publish_to_hub.py writes."""
    import numpy as np
    from core import store
    monkeypatch.setenv("HUB_DATA_DIR", str(tmp_path))
    idx = pd.bdate_range("2023-01-02", periods=800)
    walk = 300 + np.cumsum(np.random.default_rng(1).normal(0, 3, len(idx)))
    store.save_frame("credit", "spreads_bps", pd.DataFrame({"hy_spread": walk, "baa_spread": walk / 2}, index=idx))
    store.save_frame("credit", "spreads", pd.DataFrame({"hy_oas": walk / 100, "ig_oas": walk / 300}, index=idx))
    p_stress = np.linspace(0, 1, len(idx))
    store.save_frame("credit", "stress", pd.DataFrame({"regime_prob_0": (1 - p_stress) / 2, "regime_prob_1": (1 - p_stress) / 2,
                                                       "regime_prob_2": p_stress, "stress_prob": p_stress}, index=idx))
    store.save_frame("credit", "tiers", pd.DataFrame({"B": walk, "CCC": walk * 3}, index=idx))
    store.save_frame("credit", "forecast", pd.DataFrame({"forecast_bps": np.linspace(-2, 2, 60)}, index=idx[-60:]))
    card = {"bps": 300.0, "change_20d": 5.0, "percentile": 0.4, "since": "2023-01-02", "as_of": "2026-01-01"}
    tier = {"tier": "B", "spread": 300.0, "change": 12.0, "average": 290.0, "low": 250.0, "high": 400.0,
            "percentile": 0.6, "history_start": "2023-01-02"}
    store.save_json("credit", "summary", {
        "as_of": "2026-01-01", "demo": True, "spread_col": "baa_spread",
        "spreads": {"hy_spread": card, "baa_spread": card},
        "stress": {"prob": 0.6, "date": "2026-01-01", "n_states": 3},
        "exposure": {"weight": 0.4, "date": "2026-01-01", "target_vol": 0.15},
        "forecast": {"bps": 1.5, "date": "2026-01-01", "horizon": 5, "model": "ensemble", "holdout_start": "2019-01-01"},
        "tiers": [tier], "widening": {"widening": 1, "total": 1, "threshold_bp": 10.0},
        "decompression": {"value": 600.0, "change_20d": 20.0, "percentile": 0.9},
        "liquidity": {"as_of": "2026-01-01", "net": 5800.0, "net_change": -50.0, "net_change_pct": -0.9,
                      "assets": 6700.0, "assets_change": 10.0, "tga": 900.0, "tga_change": 60.0,
                      "rrp": 1.0, "rrp_change": 0.0}})


def test_credit_page_renders(tmp_path, monkeypatch):
    _fake_credit(tmp_path, monkeypatch)
    from streamlit.testing.v1 import AppTest
    page = AppTest.from_file(str(ROOT / "modules" / "credit" / "page.py"), default_timeout=60).run()
    assert not page.exception, page.exception
    assert any(m.value == "60%" for m in page.metric)  # P(stress)


def test_credit_page_without_data(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_DATA_DIR", str(tmp_path))
    from streamlit.testing.v1 import AppTest
    page = AppTest.from_file(str(ROOT / "modules" / "credit" / "page.py"), default_timeout=60).run()
    assert not page.exception
    assert page.info


def test_credit_override_feeds_market(tmp_path, monkeypatch):
    _fake_credit(tmp_path, monkeypatch)
    from modules.market import config as cfg, job
    fred = {}
    job._apply_credit_override(fred, log=lambda *a: None)
    assert fred[cfg.HY_OAS].iloc[0] == pytest.approx(fred[cfg.IG_OAS].iloc[0] * 3)


def test_macro_page_renders(tmp_path, monkeypatch):
    import numpy as np
    from core import store
    monkeypatch.setenv("HUB_DATA_DIR", str(tmp_path))
    idx = pd.date_range("1990-01-31", periods=400, freq="ME")
    store.save_frame("macro", "walk_forward", pd.DataFrame(
        {"p_recession": np.linspace(0, 1, 400), "factor_real_activity": np.sin(np.arange(400) / 9)}, index=idx))
    store.save_json("macro", "summary", {
        "run_at": "2026-01-02T18:00:00", "demo": False,
        "nowcast": {"recession_probability": 0.2, "gdp_nowcast": 2.0, "gdp_ci_lower": -1.0, "gdp_ci_upper": 5.0,
                    "current_regime": "expansion", "factor_values": {"real_activity": 0.3, "long_rates": -1.0},
                    "ensemble_detail": {"cfnai": 0.1, "probit": 0.3, "rsm": 0.5, "ensemble": 0.2},
                    "weights": {"cfnai": 0.5, "probit": 0.5, "rsm": 0.0}, "signal_as_of": {"ensemble": "2025-12-31"}},
        "panel": {"rows": 400, "start": "1990-01-31", "through": str(idx[-1].date()), "built": "2020-01-01T00:00:00"}})
    from streamlit.testing.v1 import AppTest
    page = AppTest.from_file(str(ROOT / "modules" / "macro" / "page.py"), default_timeout=60).run()
    assert not page.exception, page.exception
    assert any(m.value == "20.0%" for m in page.metric)
    assert page.warning  # panel built long ago -> staleness warning


def test_macro_page_without_data(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_DATA_DIR", str(tmp_path))
    from streamlit.testing.v1 import AppTest
    page = AppTest.from_file(str(ROOT / "modules" / "macro" / "page.py"), default_timeout=60).run()
    assert not page.exception
    assert page.info


def test_vol_page_renders(tmp_path, monkeypatch):
    import numpy as np
    from core import store
    monkeypatch.setenv("HUB_DATA_DIR", str(tmp_path))
    days = pd.bdate_range("2026-01-02", periods=60)
    ov = pd.DataFrame({"ticker": ["SPY", "NVDA"], "date": days[-1], "spot": [700.0, 180.0],
                       "atm_7d": [0.14, 0.4], "atm_30d": [0.15, 0.42], "atm_91d": [0.16, 0.41], "atm_365d": [0.18, 0.4],
                       "atm_30d_d5": [0.01, -0.02], "atm_30d_pct252": [0.6, np.nan], "rr25_30d": [-0.05, -0.04],
                       "ts_30_91": [0.01, -0.01], "vrp_30d": [0.03, 0.1], "earn_days_to": [np.nan, 12.0],
                       "fc21_vol": [0.16, 0.43], "fc21_lo80": [0.1, 0.3], "fc21_hi80": [0.22, 0.55]})
    store.save_frame("vol", "overview", ov)
    store.save_frame("vol", "history", pd.DataFrame({"date": list(days) * 2, "ticker": ["SPY"] * 60 + ["NVDA"] * 60,
                                                     "atm_30d": 0.15, "rv_cc_21d": 0.12}))
    store.save_frame("vol", "market", pd.DataFrame({"mkt_vix": np.linspace(15, 20, 60),
                                                    "mkt_vix3m": np.linspace(17, 21, 60)}, index=days))
    store.save_json("vol", "summary", {"as_of": "2026-03-26", "tickers": 2, "history_start": "2026-01-02",
                                       "stale_tickers": [], "model": "HAR", "last_health": {"ok": True},
                                       "track_record_21d": {"SPY": {"n": 10, "rmse_forecast": 5.0, "rmse_implied": 6.0,
                                                                    "bias_forecast": 1.0, "coverage80": 0.8}}})
    from streamlit.testing.v1 import AppTest
    page = AppTest.from_file(str(ROOT / "modules" / "vol" / "page.py"), default_timeout=60).run()
    assert not page.exception, page.exception
    assert page.warning  # surfaces months old -> scraper warning


def test_vol_page_without_data(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_DATA_DIR", str(tmp_path))
    from streamlit.testing.v1 import AppTest
    page = AppTest.from_file(str(ROOT / "modules" / "vol" / "page.py"), default_timeout=60).run()
    assert not page.exception
    assert page.info


def test_tailrisk_page_renders(tmp_path, monkeypatch):
    import numpy as np
    from core import store
    monkeypatch.setenv("HUB_DATA_DIR", str(tmp_path))
    store.save_frame("tailrisk", "fan", pd.DataFrame({f"p{p}": np.linspace(0, p / 1000, 21) for p in (5, 25, 50, 75, 95)},
                                                      index=pd.RangeIndex(1, 22, name="day")))
    store.save_frame("tailrisk", "pnl_hist", pd.DataFrame({"bin_mid": np.linspace(-0.2, 0.2, 80),
                                                           "unhedged": np.full(80, 1 / 80)}))
    m = {"var": 0.05, "cvar": 0.09, "mean": 0.008, "std": 0.04, "excess_kurtosis": 10.0}
    store.save_json("tailrisk", "summary", {
        "run_at": "2026-01-02T18:00:00", "demo": False, "data_through": "2026-01-02", "data_start": "2007-01-04",
        "portfolio": {"SPY": 0.6, "TLT": 0.4},
        "model": {"n_paths": 1000, "horizon_days": 21, "marginal": "student_t", "volatility": "garch",
                  "regime": "markov_2state", "dependence": "student_t_copula"},
        "simulated": {"95%": m, "99%": m}, "historical": {"95%": m, "99%": m},
        "hedges": [{"name": "unhedged", "expected_return": 0.008, "var_95": 0.05, "cvar_95": 0.09, "cvar_99": 0.15},
                   {"name": "put_0.95m", "expected_return": 0.0, "var_95": 0.055, "cvar_95": 0.07, "cvar_99": 0.1}],
        "optimal": {"alpha": 0.95, "weights": {"SPY": 0.5, "TLT": 0.5}, "cvar": 0.06, "var": 0.04,
                    "expected_return": 0.006},
        "crisis_regime": {"prob": 0.7, "long_run_share": 0.2, "vol_ratio": 2.5},
        "hedge_implied_vol": 0.18,
        "stress": [{"name": "baseline", "description": "no shock", "95%": m, "99%": m},
                   {"name": "gfc_2008", "description": "replay", "95%": m, "99%": m}]})
    from streamlit.testing.v1 import AppTest
    page = AppTest.from_file(str(ROOT / "modules" / "tailrisk" / "page.py"), default_timeout=60).run()
    assert not page.exception, page.exception
    assert any(m.value == "5.0%" for m in page.metric)
    assert any(h.value == "Stress scenarios" for h in page.subheader)


def _fake_augury(tmp_path, monkeypatch):
    """Data in the schema of augury's scripts/publish_to_hub.py (SPY with an IV view, AAPL without)."""
    import numpy as np
    from core import store
    monkeypatch.setenv("HUB_DATA_DIR", str(tmp_path))
    as_of = pd.Timestamp("2026-03-02")
    rows = []
    for t, iv in (("SPY", 0.2), ("AAPL", np.nan)):
        for h in (1, 5, 21):
            s = 0.012 * np.sqrt(h)
            rows.append({"horizon": h, "as_of": as_of, "last_price": 100.0, "vol_ann": 0.19, "var_99": -2.3 * s,
                         "var_95": -1.6 * s, "es_99": -2.8 * s, "es_95": -2.0 * s, "lo_90": 100 * (1 - 1.6 * s),
                         "median": 100.0, "hi_90": 100 * (1 + 1.6 * s), "p_up": 0.52, "model": "gjr-skewt",
                         "ticker": t, "group": "Index ETFs" if t == "SPY" else "Single stocks",
                         "gjr_vol_ann": 0.2, "realised_vol_21d": 0.17, "iv": iv,
                         "iv_symbol": "^VIX" if t == "SPY" else None})
    store.save_frame("augury", "forecast", pd.DataFrame(rows))
    fdays = pd.bdate_range(as_of + pd.offsets.BDay(1), periods=21)
    store.save_frame("augury", "bands", pd.concat([pd.DataFrame(
        {"date": fdays, **{f"q{q}": 100 + (q - 50) / 10 * np.sqrt(np.arange(1, 22)) for q in (5, 25, 50, 75, 95)},
         "ticker": t, "day": np.arange(1, 22)}) for t in ("SPY", "AAPL")], ignore_index=True))
    pdays = pd.bdate_range(end=as_of, periods=260)
    store.save_frame("augury", "prices", pd.DataFrame({"ticker": ["SPY"] * 260 + ["AAPL"] * 260,
                                                       "date": list(pdays) * 2, "close": 100.0}))
    rng = np.random.default_rng(0)
    y = rng.normal(0, 0.01, 300)
    store.save_frame("augury", "track", pd.DataFrame({
        "origin": pd.bdate_range(end=as_of, periods=300), "model": "augury", "horizon": 1, "y": y, "crps": 0.005,
        "pit": rng.uniform(size=300), "std": 0.01, "var_1": -0.023, "hit_1": y < -0.023, "var_5": -0.016,
        "hit_5": y < -0.016, "cov_50": True, "width_50": 0.013, "cov_90": True, "width_90": 0.033, "ticker": "SPY"}))
    var = {"breaches": 3, "rate": 0.01, "kupiec_p": 0.9, "christoffersen_p": 0.5, "recent_n": 250,
           "recent_breaches": 3, "recent_expected": 2.5, "recent_zone": "Green"}
    store.save_json("augury", "summary", {
        "as_of": as_of.isoformat(), "published": "2026-03-02T18:20:00", "demo": False, "augury_version": "0.2.0",
        "groups": {"Index ETFs": ["SPY"], "Single stocks": ["AAPL"]},
        "models": {"SPY": "gjr-skewt+iv0.5", "AAPL": "gjr-skewt"}, "iv_views": {"SPY": "^VIX"},
        "track_start": "2016-01-01", "errors": {"XYZ": "ValueError: not enough price history"},
        "scores": {"SPY": {"n": 300, "since": "2025-01-02", "through": "2026-03-02",
                           "var": {"0.01": var, "0.05": {**var, "rate": 0.05}},
                           "coverage_90": {"1": 0.9, "5": 0.91, "21": 0.92},
                           "coverage_50": {"1": 0.5, "5": 0.5, "21": 0.5},
                           "skill": {"1": 0.003, "5": 0.004, "21": 0.004}}}})


def test_augury_page_renders(tmp_path, monkeypatch):
    _fake_augury(tmp_path, monkeypatch)
    from streamlit.testing.v1 import AppTest
    page = AppTest.from_file(str(ROOT / "modules" / "augury" / "page.py"), default_timeout=60).run()
    assert not page.exception, page.exception
    assert page.warning  # forecasts months old -> stale warning
    assert any(m.label == "Skill vs plain GJR, 1 day" for m in page.metric)
    page.selectbox(key="aug_ticker").select("AAPL").run()  # no track record yet
    assert not page.exception, page.exception
    assert page.info


def test_augury_page_without_data(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_DATA_DIR", str(tmp_path))
    from streamlit.testing.v1 import AppTest
    page = AppTest.from_file(str(ROOT / "modules" / "augury" / "page.py"), default_timeout=60).run()
    assert not page.exception
    assert page.info


def test_tailrisk_page_without_data(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_DATA_DIR", str(tmp_path))
    from streamlit.testing.v1 import AppTest
    page = AppTest.from_file(str(ROOT / "modules" / "tailrisk" / "page.py"), default_timeout=60).run()
    assert not page.exception
    assert page.info


def test_incomplete_last_session_is_dropped(tmp_path, monkeypatch):
    """Yahoo can serve today's row half-filled; every output must stop at the last full session."""
    import numpy as np
    monkeypatch.setenv("HUB_DATA_DIR", str(tmp_path))
    from modules.market import config as cfg, demo, job
    inputs = demo.generate()
    last, prev = inputs["etf"].index[-1], inputs["etf"].index[-2]
    inputs["etf"].loc[last, cfg.BENCHMARK] = np.nan          # no SPY close today
    stocks = inputs["stocks"]
    stocks.loc[last, stocks.columns[: len(stocks.columns) // 2]] = np.nan  # half the stocks missing
    out = job.build(inputs, log=lambda *a: None)
    assert out["breadth"].index[-1] == prev
    assert (out["etf_returns"]["date"] == prev).all()
    assert out["meta"]["as_of"] == prev.strftime("%b %d, %Y")


def test_changes_and_market_link_math():
    import numpy as np
    from modules.market.indicators import changes, market_link
    idx = pd.bdate_range("2010-01-01", periods=3000)
    rng = np.random.default_rng(0)
    price = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, len(idx)))), index=idx)

    ch = changes(pd.Series(np.arange(30.0), index=idx[:30]), idx[29], {"1 week": 5})
    assert ch["1 week"]["prior"] == 24 and ch["1 week"]["change"] == 5

    # a gauge that *is* the next 21-day return: perfect foresight, so the link is ~1 and reliable
    fwd = price.shift(-21) / price - 1
    out = market_link(fwd.dropna(), price, horizon=21, cuts=[0.0])
    assert out["predictive"] > 0.95 and out["significant"]
    assert out["bands"][1]["mean"] > 0 > out["bands"][0]["mean"]
    # the same gauge only known 21 days later has no edge left
    late = market_link(fwd.dropna(), price, horizon=21, cuts=[0.0], lag=21)
    assert abs(late["predictive"]) < 0.3
    # a gauge that is the price itself moves with the market, but noise says nothing about the future
    assert market_link(price, price, horizon=21, cuts=[100.0])["coincident"] > 0.95
    noise = pd.Series(rng.normal(size=len(idx)), index=idx)
    assert not market_link(noise, price, horizon=21, cuts=[0.0])["significant"]


def test_gauges_carry_trend_and_market_link(demo_data):
    from core import store
    gauges = store.load_json("market", "gauges")
    for key in ("fear_greed", "liquidity", "technical"):
        assert set(gauges[key]["trend"]) == {"1 week", "1 month"}, key
        assert gauges[key]["vs_spy"]["n_coincident"] > 0, key
    assert set(gauges["economic"]["trend"]) == {"1 month", "3 months"}
    assert "spy" in store.load_frame("market", "gauge_history")


def test_hub_forgets_modules_edited_while_running(tmp_path, monkeypatch):
    """Editing a module under the hub while the server runs must not leave pages on stale code."""
    import os
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    helper = src[src.index("def forget_changed_modules"):src.index("forget_changed_modules()\n")]
    ns = {"os": os, "sys": sys, "ROOT": ROOT}
    exec(helper, ns)  # just the helper: running app.py itself would start Streamlit navigation
    forget = ns["forget_changed_modules"]

    import modules.credit.config as cfg_mod
    forget()                                   # first sight: stamps the import time
    assert "modules.credit.config" in sys.modules
    path = cfg_mod.__file__
    old = os.path.getmtime(path)
    try:
        os.utime(path, (old + 5, old + 5))     # "edited" after import
        assert "modules.credit.config" in forget()
        assert "modules.credit.config" not in sys.modules
        from modules.credit import config as fresh  # the pages' form: must not reuse the package attribute
        assert fresh is not cfg_mod
    finally:
        os.utime(path, (old, old))


def test_analog_engine_finds_planted_lookalike():
    import numpy as np
    from modules.analogs.engine import find_analogs
    idx = pd.bdate_range("2000-01-03", periods=2000)
    rng = np.random.default_rng(1)
    state = pd.DataFrame(rng.normal(size=(len(idx), 4)), index=idx, columns=list("abcd"))
    state.iloc[500] = state.iloc[-1] + 0.01          # a near-copy of today, far in the past
    state.iloc[-30] = state.iloc[-1]                  # an exact copy too recent to have known outcomes
    w = dict.fromkeys("abcd", 1.0)
    an, used = find_analogs(state, idx[-1], w, k=10, separation=63, min_gap=63, min_features=4)
    assert an.index[0] == idx[500] and used == list("abcd")
    assert idx[-30] not in an.index                    # outcomes unknown -> not a candidate
    pos = sorted(state.index.get_indexer(an.index))
    assert all(b - a > 63 for a, b in zip(pos, pos[1:]))  # distinct episodes
    assert an.index.max() <= idx[-64]


def test_analogs_job_and_page_on_demo(demo_data):
    from modules.analogs import job
    s = job.run(demo=True, log=lambda *a: None)       # demo has no credit spreads: runs without HY features
    assert s["analogs"] and not any(f["key"].startswith("hy") for f in s["features"])
    from streamlit.testing.v1 import AppTest
    page = AppTest.from_file(str(ROOT / "modules" / "analogs" / "page.py"), default_timeout=60).run()
    assert not page.exception, page.exception


def test_analogs_page_without_data(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_DATA_DIR", str(tmp_path))
    from streamlit.testing.v1 import AppTest
    page = AppTest.from_file(str(ROOT / "modules" / "analogs" / "page.py"), default_timeout=60).run()
    assert not page.exception
    assert page.info


def test_analyst_tools_on_demo(demo_data):
    import json
    from modules.analogs import job as analogs_job
    from modules.analyst import agent, tools
    analogs_job.run(demo=True, log=lambda *a: None)
    assert "error" not in tools.market_overview() and "error" not in tools.lookalikes()
    assert tools.gauge_detail("liquidity")["components"]
    assert "available" in tools.series_history("nope")
    assert tools.series_history("spy", 1)["points"]
    assert "error" in tools.credit_overview()          # not published in demo: a message, not a crash
    for t in agent.TOOLS:                              # every tool result is valid JSON
        args = {"gauge": "technical"} if t.name == "gauge_detail" else {"name": "vix"} if t.name == "series_history" else {}
        json.loads(t.call(args) if hasattr(t, "call") and t.name else t(**args))


def test_analyst_tools_explain_lags_and_gaps(demo_data):
    import numpy as np
    from core import store
    from modules.analyst import tools
    econ = tools.data_freshness()["as_of"]["economic_gauge"]
    assert econ["final_month"] and "release lag" in econ["note"]
    assert tools.market_overview()["gauges"]["economic"]["release_status"] == econ
    days = pd.bdate_range("2026-01-02", periods=5)
    store.save_frame("vol", "overview", pd.DataFrame({"ticker": ["SPY", "HYG"], "date": days[-1],
                                                      "atm_30d": [0.15, np.nan], "atm_30d_d5": [0.01, np.nan]}))
    store.save_frame("vol", "history", pd.DataFrame({"date": list(days) * 2, "ticker": ["SPY"] * 5 + ["HYG"] * 5,
                                                     "atm_30d": [0.15] * 5 + [0.06, 0.07, 0.05, np.nan, np.nan]}))
    store.save_json("vol", "summary", {"as_of": "2026-01-08"})
    rows = tools.vol_overview()["tickers_vol_pts"]
    assert rows["HYG"]["iv_30d_last_available"] == {"date": "2026-01-06", "value": 5.0}
    assert "iv_30d_last_available" not in rows["SPY"]


class _Msg:
    def __init__(self, content, stop, usage=(100, 20)):
        from types import SimpleNamespace as NS
        self.content = content
        self.stop_reason = stop
        self.model = "claude-opus-5-5"
        self.usage = NS(input_tokens=usage[0], output_tokens=usage[1], cache_read_input_tokens=50,
                        cache_creation_input_tokens=0)


def _fake_client(messages):
    from types import SimpleNamespace as NS
    seen = {}

    def tool_runner(**kw):
        seen.update(kw)
        return iter(messages)
    return NS(beta=NS(messages=NS(tool_runner=tool_runner))), seen


def test_analyst_agent_loop_with_fake_client():
    from types import SimpleNamespace as NS
    from modules.analyst import agent, config as acfg
    msgs = [_Msg([NS(type="tool_use", name="market_overview", input={})], "tool_use"),
            _Msg([NS(type="thinking"), NS(type="text", text="All calm.")], "end_turn")]
    client, seen = _fake_client(msgs)
    res = agent.ask([{"role": "user", "content": "hi"}], effort="medium", client=client)
    assert res["text"] == "All calm." and res["tool_calls"] == [{"name": "market_overview", "input": {}}]
    assert res["usage"]["input_tokens"] == 200 and res["usage"]["cache_read_input_tokens"] == 100
    assert seen["model"] == acfg.MODEL and seen["output_config"] == {"effort": "medium"}
    assert seen["fallbacks"] == "default" and acfg.FALLBACK_BETA in seen["betas"]
    client, _ = _fake_client([_Msg([NS(type="text", text="partial")], "max_tokens")])
    assert "output limit" in agent.ask([], "low", client=client)["text"]

    def no_auth(**kw):
        raise TypeError("Could not resolve authentication method. Expected one of api_key, ...")
    with pytest.raises(agent.NoCredentials):
        agent.ask([], "low", client=NS(beta=NS(messages=NS(tool_runner=no_auth))))


def test_analyst_job_skips_without_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_DATA_DIR", str(tmp_path))
    from modules.analyst import agent, job

    def no_creds(*a, **k):
        raise agent.NoCredentials("none")
    monkeypatch.setattr(agent, "ask", no_creds)
    lines = []
    assert job.run(log=lines.append) is None and any("ANTHROPIC_API_KEY" in line for line in lines)
    assert job.run(demo=True, log=lines.append) is None


def test_analyst_page_brief_and_chat(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_DATA_DIR", str(tmp_path))
    from core import store
    from streamlit.testing.v1 import AppTest
    page_path = str(ROOT / "modules" / "analyst" / "page.py")
    empty = AppTest.from_file(page_path, default_timeout=60).run()
    assert not empty.exception and empty.info

    brief = {"generated": "2026-10-27T18:20:00", "data_as_of": "Oct 27, 2026", "model": "claude-opus-5-5",
             "text": "## What changed\nLiquidity tightened.", "stop_reason": "end_turn",
             "tool_calls": [{"name": "market_overview", "input": {}}], "usage": {"input_tokens": 10, "output_tokens": 5}}
    store.save_json("analyst", "brief", brief)
    store.save_json("analyst", "brief_history", [brief])
    from modules.analyst import agent
    asked = {}

    def fake_ask(messages, effort, client=None):
        asked["messages"] = messages
        return {"text": "Because spreads widened.", "stop_reason": "end_turn", "usage": {},
                "tool_calls": [{"name": "credit_overview", "input": {}}], "model": "claude-opus-5-5"}
    monkeypatch.setattr(agent, "ask", fake_ask)
    at = AppTest.from_file(page_path, default_timeout=60).run()
    assert not at.exception and any("Liquidity tightened" in m.value for m in at.markdown)
    at.chat_input[0].set_value("Why is liquidity tight?").run()
    assert not at.exception
    assert "Liquidity tightened" in asked["messages"][0]["content"]       # brief passed as context
    assert any(m.value == "Because spreads widened." for m in at.markdown)


def test_analyst_failure_is_recorded_and_shown(tmp_path, monkeypatch):
    from types import SimpleNamespace as NS

    import anthropic
    monkeypatch.setenv("HUB_DATA_DIR", str(tmp_path))
    from core import store
    from modules.analyst import agent, job
    from streamlit.testing.v1 import AppTest
    page_path = str(ROOT / "modules" / "analyst" / "page.py")
    brief = {"generated": "2026-11-06T18:20:00", "data_as_of": "Nov 06, 2026", "model": "claude-opus-5-5",
             "text": "Old brief.", "stop_reason": "end_turn", "tool_calls": [], "usage": {}}
    store.save_json("analyst", "brief", brief)
    store.save_json("analyst", "brief_history", [brief])

    def rejected(*a, **k):
        resp = NS(status_code=401, headers={}, request=NS(method="POST", url="https://api.anthropic.com/v1/messages"))
        raise anthropic.AuthenticationError("invalid x-api-key", response=resp,
                                            body={"error": {"message": "invalid x-api-key"}})
    monkeypatch.setattr(agent, "ask", rejected)
    with pytest.raises(RuntimeError, match="rejected the key"):   # still fails the job in run_jobs
        job.run(log=lambda *a: None)
    assert store.load_json("analyst", "last_attempt")["ok"] is False
    at = AppTest.from_file(page_path, default_timeout=60).run()
    assert not at.exception and "No new brief since Nov 06" in at.warning[0].value
    assert "ANTHROPIC_API_KEY" in at.warning[0].value

    monkeypatch.setattr(agent, "ask", lambda *a, **k: {"text": "New brief.", "stop_reason": "end_turn", "usage": {},
                                                       "tool_calls": [], "model": "claude-opus-5-5"})
    job.run(log=lambda *a: None)
    at = AppTest.from_file(page_path, default_timeout=60).run()
    assert not at.exception and not at.warning                    # a success clears it


def test_launch_page_starts_app_then_forwards(tmp_path, monkeypatch):
    """A sidebar link to a stopped app starts it once, waits for the port, then forwards."""
    monkeypatch.setenv("HUB_DATA_DIR", str(tmp_path))
    from streamlit.testing.v1 import AppTest
    from core import apps
    started = []

    class Proc:
        returncode = None

        def poll(self):
            return None

    def fake_start(app, port):
        started.append(port)
        return Proc()

    monkeypatch.setattr(apps, "is_up", lambda port, timeout=0.5: bool(started))
    monkeypatch.setattr(apps, "missing", lambda app: None)
    monkeypatch.setattr(apps, "start", fake_start)
    page = AppTest.from_file(str(ROOT / "views" / "launch.py"), default_timeout=30)
    page.query_params["app"] = "8502"
    page.run()
    assert not page.exception and not page.error
    assert started == [8502]
    assert page.link_button[0].url == "http://localhost:8502"

    page = AppTest.from_file(str(ROOT / "views" / "launch.py"), default_timeout=30)  # already up
    page.query_params["app"] = "8502"
    page.run()
    assert started == [8502] and page.link_button[0].url == "http://localhost:8502"

    page = AppTest.from_file(str(ROOT / "views" / "launch.py"), default_timeout=30)
    page.query_params["app"] = "9999"
    page.run()
    assert page.error and started == [8502]


def test_job_for_missing_project_is_skipped(tmp_path, monkeypatch):
    """A project that isn't cloned is skipped with a note, not counted as a failure."""
    import argparse
    import run_jobs
    monkeypatch.setenv("HUB_DATA_DIR", str(tmp_path))
    gone = tmp_path / "not-cloned"
    monkeypatch.setattr(run_jobs, "JOBS", {"other": {"cmd": [str(gone / ".venv" / "python.exe"), "x.py"],
                                                     "cwd": str(gone)}})
    (tmp_path / "logs").mkdir()
    assert run_jobs.run_all(argparse.Namespace(only=None, demo=True), tmp_path / "logs") == 0
    assert "other skipped" in (tmp_path / "logs" / "jobs.log").read_text(encoding="utf-8")


def test_no_math_escapes_dollars():
    from core import ui
    assert ui.no_math("fell $114bn, TGA rose $122bn") == r"fell \$114bn, TGA rose \$122bn"
    assert ui.no_math(r"already \$5") == r"already \$5"


def test_rotation_math():
    import numpy as np
    from modules.market import indicators as ind
    weeks = pd.date_range("2015-01-02", periods=300, freq="W-FRI")
    t = np.arange(300)
    bench = pd.Series(100.0, index=weeks)
    prices = pd.DataFrame({"CYCLE": 100 * np.exp(0.05 * np.sin(2 * np.pi * t / 40)),  # 40-week swing vs SPY
                           "RISER": 100 * np.exp(0.002 * t + 0.01 * np.sin(t))}, index=weeks)
    lr = ind.log_ratio(prices, bench)
    x, y = ind.rotation_axes(lr, trend=10, momentum=2, z_weeks=52)
    assert x["RISER"].iloc[-1] > 0  # steadily outperforming: right of centre
    q = ind.quadrant(x, y)["CYCLE"].dropna()
    steps = (q.diff().dropna() % 4)
    moves = steps[steps != 0]
    assert (moves == 1).mean() > 0.9  # a swing in relative strength rotates clockwise
    assert ind.clock_angle(1.0, 1.0) == pytest.approx(45) and ind.clock_angle(-1.0, 1.0) == pytest.approx(315)

    rng = np.random.default_rng(0)
    fwd = pd.DataFrame(rng.normal(size=(40, 8)), index=pd.RangeIndex(40))
    assert ind.cross_ic(fwd, fwd, step=4).round(9).eq(1).all()
    assert len(ind.cross_ic(fwd, fwd, step=4)) == 10
    assert ind.ic_summary(ind.cross_ic(-fwd, fwd))["ic"] == pytest.approx(-1)


def test_rotation_outputs_on_demo(demo_data):
    from core import store
    from modules.market import config as cfg
    now = store.load_frame("market", "rotation_now")
    path = store.load_frame("market", "rotation_path")
    stats = store.load_json("market", "rotation_stats")
    assert set(now["group"]) == set(cfg.ROTATION_GROUPS)
    assert now["quadrant"].isin(["Leading", "Weakening", "Lagging", "Improving"]).all()
    assert now["angle"].between(0, 360).all() and now["rel_rsi"].between(0, 100).all()
    assert path.groupby(["group", "ticker"]).size().max() <= cfg.ROTATION_TAIL_WEEKS + 1
    # each quadrant label matches the signs of its own coordinates
    right, up = now["x"] >= 0, now["y"] >= 0
    assert (now.loc[right & up, "quadrant"] == "Leading").all()
    assert (now.loc[~right & ~up, "quadrant"] == "Lagging").all()
    sectors = stats["groups"]["Sectors"]
    assert len(sectors["candidates"]) == len(cfg.ROTATION_CANDIDATES)
    assert sectors["periods"]["after"]["moves"]


def test_sector_internals_and_contributions_math():
    import numpy as np
    from modules.market import indicators as ind
    days = pd.bdate_range("2024-01-01", periods=300)
    t = np.arange(300)
    closes = pd.DataFrame({"UP1": 100 * 1.002 ** t, "UP2": 100 * 1.003 ** t, "DOWN": 100 * 0.999 ** t,
                           "OTHER": 100.0 + 0 * t}, index=days)
    sector_of = pd.Series({"UP1": "XLA", "UP2": "XLA", "DOWN": "XLA", "OTHER": "XLB"})
    bench = pd.Series(100 * 1.001 ** t, index=days)
    caps = pd.Series({"UP1": 300.0, "UP2": 100.0, "DOWN": 600.0, "OTHER": 50.0})
    part = ind.sector_internals(closes, sector_of, bench, caps, window=20)
    last = part[part["date"] == days[-1]].set_index("sector")
    assert last.at["XLA", "beating"] == pytest.approx(200 / 3)  # two of three beat the benchmark
    assert last.at["XLA", "above_200"] == pytest.approx(200 / 3)
    assert last.at["XLA", "net_highs"] == pytest.approx(100 / 3)  # two at highs, one at lows
    c = ind.contributions(closes, sector_of, bench, caps, window=20)
    xla = c[c["sector"] == "XLA"]
    assert xla["weight"].sum() == pytest.approx(100)
    # contributions add up to the cap-weighted sector return minus the benchmark's
    assert xla["contrib"].sum() == pytest.approx(last.at["XLA", "rel_cw"], rel=1e-6)
    assert xla.set_index("ticker").at["DOWN", "contrib"] < 0


def test_cross_asset_check_signs():
    import numpy as np
    from modules.market import indicators as ind
    weeks = pd.date_range("2020-01-03", periods=200, freq="W-FRI")
    rng = np.random.default_rng(1)
    drv = pd.Series(4 + np.cumsum(rng.normal(0, 0.1, 200)), index=weeks)  # a yield, in %
    rel = -0.05 * drv + pd.Series(rng.normal(0, 0.001, 200), index=weeks).cumsum()  # falls when yields rise
    out = ind.cross_asset_check(rel, drv, "fred", sign=-1, weeks=13, corr_weeks=52)
    assert out["corr_all"] > 0.9 and out["corr_recent"] > 0.9  # signed: positive = moves the expected way
    assert out["agrees"] == (np.sign(out["rel_change"]) == -np.sign(out["driver_change"]))
    d = ind.dispersion(pd.DataFrame({k: 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 400)))
                                     for k in "ABCD"}, index=pd.bdate_range("2023-01-02", periods=400)))
    assert d["correlation"].dropna().abs().lt(0.5).all() and (d["dispersion"].dropna() > 0).all()


def test_sector_extras_on_demo(demo_data):
    from core import store
    from modules.market import config as cfg
    internals = store.load_frame("market", "sector_internals")
    assert set(internals["sector"]) == set(cfg.GICS_TO_ETF.values())
    assert internals[["beating", "above_50", "above_200"]].dropna().stack().between(0, 100).all()
    contrib = store.load_frame("market", "sector_contrib")
    assert set(contrib["window"]) == set(cfg.CONTRIBUTION_WINDOWS)
    assert set(store.load_json("market", "sector_confirmation")) >= {"rising_broad", "falling_narrow", "ic_beating"}
    assert store.load_frame("market", "sector_leadership").shape == (cfg.LEADERSHIP_WEEKS, len(cfg.SECTORS))
    pairs = store.load_json("market", "cross_asset")["pairs"]
    assert {p["sector"] for p in pairs} == {c["sector"] for c in cfg.CROSS_ASSET}


def test_fund_flows_ignore_splits_and_launches():
    import numpy as np
    from modules.market import indicators as ind
    days = pd.bdate_range("2024-01-01", periods=120)
    shares = np.full(120, 1e8)
    shares[100:] += 1e6  # a real creation: 1% more shares
    nav = np.full(120, 50.0)
    shares[110:] *= 2  # a 2-for-1 split
    nav[110:] /= 2
    hist = pd.DataFrame({"date": days, "ticker": "XLX", "nav": nav, "shares": shares, "tna": nav * shares})
    flows, tna = ind.fund_flows(hist)
    f = flows["XLX"]
    assert f.iloc[:63].isna().all()  # launch quarter left out
    assert f.iloc[100] == pytest.approx(1e6 * 50)
    assert f.iloc[110] == 0  # the split is not money
    assert ind.flow_share(flows, tna, 20)["XLX"].iloc[105] == pytest.approx(1e6 * 50 / (1e8 * 50) * 100)


def test_flows_on_demo(demo_data):
    from core import store
    from modules.market import config as cfg
    summary = store.load_json("market", "flows_summary")
    assert {r["ticker"] for r in summary["rows"]} == set(cfg.FLOW_TICKERS)
    assert set(summary["stats"]["signals"]) == {"4 wk", "13 wk"}
    assert not store.load_frame("market", "flows_history").empty


def test_market_page_with_nyse_breadth(demo_data):
    """TickerLake's breadth publisher output (fake, same schema: the hub's breadth() plus stocks and
    provisional) shows as the default universe, and the S&P 500 view is still one click away."""
    import numpy as np
    from streamlit.testing.v1 import AppTest
    from core import store
    from modules.market import indicators as ind
    days = pd.bdate_range("2025-01-02", periods=300)
    rng = np.random.default_rng(3)
    closes = pd.DataFrame(100 * np.exp(rng.normal(0, 0.01, (300, 40)).cumsum(axis=0)), index=days,
                          columns=[f"S{i}" for i in range(40)])
    nyse = ind.breadth(closes)
    nyse["stocks"] = 40
    nyse["provisional"] = 0
    nyse.loc[nyse.index[-1], "provisional"] = 12
    store.save_frame("breadth", "nyse", nyse)
    page = AppTest.from_file(str(ROOT / "modules" / "market" / "page.py"), default_timeout=60).run()
    assert not page.exception, page.exception
    assert any("NYSE common stocks" in c.value and "12 of the latest closes" in c.value for c in page.caption)
    from modules.analyst import tools
    assert tools.market_overview()["breadth_nyse_all_common"]["pct_advancing"] is not None


def test_market_page_with_revisions(demo_data):
    """TickerLake's publisher output (fake, same schema) shows on the market page."""
    from streamlit.testing.v1 import AppTest
    from core import store
    from modules.market import config as cfg
    sectors = list(cfg.GICS_TO_ETF)
    store.save_frame("revisions", "sector_revisions", pd.DataFrame({
        "gics_sector": sectors, "names": 10, "rev_30d": 0.5, "rev_90d": 1.0, "rising_share": 60.0,
        "breadth": 20.0, "upgrades": 3, "downgrades": 1, "targets_raised": 9, "targets_cut": 4}))
    store.save_frame("revisions", "revisions_names", pd.DataFrame({
        "symbol": ["AAA", "BBB"], "rev_30d": [5.0, -3.0], "rev_90d": [6.0, -4.0], "up_30d": [4, 0],
        "down_30d": [0, 3], "gics_sector": sectors[0], "name": ["A Co", "B Co"]}))
    dates = pd.date_range("2026-11-02", periods=6)
    store.save_frame("revisions", "revisions_history", pd.DataFrame(
        [{"snapshot_date": d, "gics_sector": g, "names": 10, "rev_30d": 0.1, "rev_90d": 0.2,
          "rising_share": 50.0, "breadth": 5.0} for d in dates for g in sectors]))
    store.save_json("revisions", "summary", {"snapshot_date": "2026-11-07", "snapshots": 6,
                                             "first_snapshot": "2026-11-02", "members": 503, "covered": 501,
                                             "action_days": 30})
    page = AppTest.from_file(str(ROOT / "modules" / "market" / "page.py"), default_timeout=60).run()
    assert not page.exception, page.exception
    assert any("Estimate revisions" in m.value for m in page.markdown)


def _fake_events(store):
    """TickerLake's publish_events_to_hub.py output (fake, same schema)."""
    import json
    day = pd.Timestamp("2026-11-12")
    cal = pd.DataFrame({"release_date": [pd.Timestamp("2026-11-13").date(), pd.Timestamp("2026-11-25").date()],
                        "time_et": ["08:30", "14:00"], "name": ["PPI", "FOMC rate decision"],
                        "importance": ["medium", "high"], "release_key": ["ppi", "fomc"]})
    base = {"close_time": pd.Timestamp("2026-11-13T13:29:00Z"), "volume_24h": 10.0, "below_range": False,
            "above_range": False, "pct": True}
    odds = pd.DataFrame([
        {**base, "release_key": "ppi", "release_date": cal["release_date"][0], "venue": "kalshi", "series": "KXUSPPI",
         "event_id": "KXUSPPI-26OCT", "event_title": "PPI MoM in October", "volume": 1000.0, "url": "https://kalshi.com",
         "kind": "ladder", "median": 0.42, "top": None, "top_prob": None,
         "detail": json.dumps({"strikes": [0.2, 0.4, 0.6], "p_above": [0.9, 0.55, 0.1]})},
        {**base, "release_key": "fomc", "release_date": cal["release_date"][1], "venue": "polymarket",
         "series": "fed-rates", "event_id": "fed-dec", "event_title": "Fed Decision in December?", "volume": 5e6,
         "url": "https://polymarket.com", "kind": "outcomes", "median": None, "top": "25 bps increase",
         "top_prob": 0.88, "pct": False,
         "detail": json.dumps({"outcomes": ["25 bps increase", "No change"], "probs": [0.88, 0.12]})},
    ])
    assets = pd.DataFrame([
        {**base, "underlying": "SPY", "venue": "polymarket", "series": "stocks", "event_id": "spy-week",
         "event_title": "What will S&P 500 (SPY) hit Week of November 9 2026?", "volume": 3000.0,
         "url": "https://polymarket.com", "kind": "touch", "median": None, "top": None, "top_prob": None, "pct": False,
         "detail": json.dumps({"up": [[770.0, 0.07]], "down": [[740.0, 0.2]]})},
        {**base, "underlying": "SPY", "venue": "polymarket", "series": "stocks", "event_id": "spy-close",
         "event_title": "S&P 500 (SPY) closes above ___ on November 13?", "volume": 2000.0,
         "url": "https://polymarket.com", "kind": "ladder", "median": 759.9, "top": None, "top_prob": None,
         "pct": False, "detail": json.dumps({"strikes": [750.0, 760.0, 770.0], "p_above": [0.8, 0.5, 0.1]})},
    ])
    fed = pd.DataFrame({"meeting": [pd.Timestamp("2026-12-09").date()] * 2, "venue": ["kalshi", "polymarket"],
                        "event_id": ["k", "p"], "event_title": "Fed", "url": "u", "cut": [0.01, 0.005],
                        "hold": [0.03, 0.02], "hike": [0.96, 0.975], "volume": [1e7, 3e7]})
    other = assets.iloc[:0].assign(event_title=["US recession by end of 2026?"], kind=["binary"], top=["Yes"],
                                   top_prob=[0.02], volume_24h=[2e4], url=["https://polymarket.com"])
    history = pd.DataFrame({"snapshot_date": [day.date(), (day + pd.Timedelta(days=1)).date()], "venue": "kalshi",
                            "event_id": "KXUSPPI-26OCT", "median": [0.40, 0.42], "top": None, "top_prob": None})
    for name, df in {"calendar": cal, "odds": odds, "assets": assets, "fed": fed, "other": other,
                     "history": history}.items():
        store.save_frame("events", name, df)
    store.save_json("events", "summary", {"snapshot_date": "2026-11-12", "snapshots": 2, "first_snapshot": "2026-11-12",
                                          "releases": 2, "matched_events": 2, "asset_events": 2})


def test_events_page(demo_data):
    from streamlit.testing.v1 import AppTest
    from core import store
    _fake_events(store)
    page = AppTest.from_file(str(ROOT / "modules" / "events" / "page.py"), default_timeout=60).run()
    assert not page.exception, page.exception
    cal = page.dataframe[0].value
    assert "K PPI m/m: median +0.42%" in set(cal["Markets say"])
    assert "PM Fed Decision in December: 25 bps increase (88%)" in set(cal["Markets say"])
    page.selectbox[0].set_value(page.selectbox[0].options[1]).run()  # the Fed detail: outcome bars
    assert not page.exception, page.exception
    assert any("from the last close" in m.value for m in page.markdown)  # SPY ladder vs the hub's last price


def test_events_page_without_data(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_DATA_DIR", str(tmp_path))
    from streamlit.testing.v1 import AppTest
    page = AppTest.from_file(str(ROOT / "modules" / "events" / "page.py"), default_timeout=60).run()
    assert not page.exception and page.info
