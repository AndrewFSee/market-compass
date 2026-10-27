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
        "crisis_regime": {"prob": 0.7, "long_run_share": 0.2, "vol_ratio": 2.5}})
    from streamlit.testing.v1 import AppTest
    page = AppTest.from_file(str(ROOT / "modules" / "tailrisk" / "page.py"), default_timeout=60).run()
    assert not page.exception, page.exception
    assert any(m.value == "5.0%" for m in page.metric)


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
        import modules.credit.config  # noqa: F401  re-imported fresh
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
