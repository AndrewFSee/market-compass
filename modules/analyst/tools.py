"""Read-only views of the hub's published data, sized for an LLM to read.

Plain functions returning JSON-safe dicts (no Streamlit, no network), so they are testable
without the API. agent.py wraps them as tools. Every number the analyst quotes should come
from one of these."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from core import store


def _r(x, digits: int = 2):
    """Round floats (recursively) so tool results stay short; NaN/inf -> None."""
    if isinstance(x, dict):
        return {k: _r(v, digits) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_r(v, digits) for v in x]
    if isinstance(x, (np.floating, float)):
        return None if not math.isfinite(float(x)) else round(float(x), digits)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, pd.Timestamp):
        return x.strftime("%Y-%m-%d")
    return x


def data_freshness() -> dict:
    """When each module last published, plus each module's own as-of date."""
    out = {"published_utc": {m: max(v.values()) for m, v in store.manifest().items()}}
    meta = store.load_json("market", "meta") or {}
    out["as_of"] = {
        "market_prices": meta.get("as_of"),
        "credit": (store.load_json("credit", "summary") or {}).get("as_of"),
        "vol_surfaces": (store.load_json("vol", "summary") or {}).get("as_of"),
        "macro_panel": ((store.load_json("macro", "summary") or {}).get("panel") or {}).get("through"),
        "tail_risk_data": (store.load_json("tailrisk", "summary") or {}).get("data_through"),
        "lookalikes": (store.load_json("analogs", "summary") or {}).get("as_of"),
    }
    return out


def market_overview() -> dict:
    """The four regime gauges (value, band, trend, measured link to the S&P 500), breadth, style/size
    returns and the leading and lagging sectors."""
    g = store.load_json("market", "gauges") or {}
    gauges = {}
    for k, v in g.items():
        link = v.get("vs_spy") or {}
        gauges[k] = {
            "title": v["title"], "value": v["value"], "label": v["label"], "date": v["date"],
            "scale": [v["lo"], v["hi"]], "band_cuts": v["cuts"],
            "trend": {lab: {"prior": t["prior"], "change": t["change"]} for lab, t in (v.get("trend") or {}).items()},
            "moves_with_market_r": link.get("coincident"),
            "next_period_link": link.get("predictive"), "next_period": link.get("horizon_label"),
            "next_period_link_reliable": link.get("significant"), "independent_periods": link.get("n_predictive"),
        }
    out = {"as_of": (store.load_json("market", "meta") or {}).get("as_of"), "gauges": gauges}
    b = store.load_frame("market", "breadth")
    if b is not None and len(b) > 21:
        last, wk, mo = b.iloc[-1], b.iloc[-6], b.iloc[-22]
        out["breadth_sp500"] = {
            "date": b.index[-1], **{f"pct_above_{n}d": last[f"above_{n}"] for n in (20, 50, 200)},
            "pct_above_50d_1w_ago": wk["above_50"], "pct_above_50d_1m_ago": mo["above_50"],
            "new_highs": last["new_highs"], "new_lows": last["new_lows"], "pct_advancing": last["pct_adv"],
        }
    r = store.load_frame("market", "etf_returns")
    if r is not None:
        from modules.market import config as mcfg
        grid = {f"{size} {style}": t for size, row in mcfg.STYLE_GRID.items() for style, t in row.items()}
        out["style_size_returns_pct"] = {name: {tf: r.at[t, tf] for tf in ("5D", "20D", "YTD")}
                                         for name, t in grid.items() if t in r.index}
        sec = r.loc[[t for t in mcfg.SECTORS if t in r.index], "20D"].sort_values()
        out["sectors_20d_pct"] = {"leading": {mcfg.SECTORS[t]: sec[t] for t in sec.index[-3:][::-1]},
                                  "lagging": {mcfg.SECTORS[t]: sec[t] for t in sec.index[:3]},
                                  "sp500": r.at[mcfg.BENCHMARK, "20D"] if mcfg.BENCHMARK in r.index else None}
    return _r(out)


def gauge_detail(gauge: str) -> dict:
    """One gauge in full: components with readings and scores, and S&P 500 returns by gauge band."""
    g = (store.load_json("market", "gauges") or {}).get(gauge)
    if not g:
        return {"error": f"unknown gauge '{gauge}'; use fear_greed, liquidity, technical or economic"}
    link = g.get("vs_spy") or {}
    return _r({"title": g["title"], "value": g["value"], "label": g["label"], "caption": g["caption"],
               "components": g["components"], "trend": g.get("trend"),
               "next_period_return_by_band": {"cuts": g["cuts"], "bands": link.get("bands"),
                                              "all": link.get("overall"), "since": link.get("start"),
                                              "publication_lag_periods": link.get("lag")}})


def credit_overview() -> dict:
    """Credit spreads, the real-time stress regime, overlay weight, rating tiers and Fed liquidity."""
    s = store.load_json("credit", "summary")
    if not s:
        return {"error": "no credit data published"}
    out = {k: s.get(k) for k in ("as_of", "spreads", "stress", "exposure", "forecast", "widening",
                                 "decompression")}
    if s.get("liquidity"):  # say what the *_change fields cover, or they read as weekly
        out["fed_liquidity_usd_bn"] = {**s["liquidity"], "changes_are_over": "13 weeks"}
    out["tiers"] = [{k: t[k] for k in ("tier", "spread", "change", "percentile")} for t in s.get("tiers", [])]
    st = store.load_frame("credit", "stress")
    if st is not None:
        last = st.dropna(how="all").iloc[-1]
        out["regime_probabilities_now"] = {"calm": last.get("regime_prob_0"), "elevated": last.get("regime_prob_1"),
                                           "stressed": last.get("regime_prob_2")}
    out["model_notes"] = ("Stress regime: 3-state HMM on Baa spread levels, refitted each January; probabilities "
                          "are near all-or-nothing and January refits can flip the regime with the spread "
                          "unchanged. Tier percentiles cover only FRED's ~3-year window.")
    return _r(out)


def macro_overview() -> dict:
    """Live recession probability, its signals, GDP nowcast and the walk-forward recession history."""
    s = store.load_json("macro", "summary")
    if not s:
        return {"error": "no macro data published"}
    now = s.get("nowcast") or {}
    out = {"run_at": s.get("run_at"), "live": {k: now.get(k) for k in (
        "recession_probability", "current_regime", "gdp_nowcast", "gdp_ci_lower", "gdp_ci_upper",
        "ensemble_detail", "weights", "factor_values", "signal_as_of")}}
    wf = store.load_frame("macro", "walk_forward")
    if wf is not None and "p_recession" in wf:
        p = wf["p_recession"].dropna()
        out["walk_forward_p_recession_last_6_months"] = {d.strftime("%Y-%m"): v for d, v in p.tail(6).items()}
        out["panel"] = s.get("panel", {}) and {k: s["panel"][k] for k in ("through", "built", "rows")}
    out["model_notes"] = ("A coincident recession detector (AUC ~0.94 in real time), not a forecaster: at 12 months "
                          "it is at chance, it showed no skill on equity returns, and it missed COVID.")
    return _r(out, 3)


def vol_overview(tickers: list[str] | None = None) -> dict:
    """Market vol indices with 5-day changes, the biggest 5-day moves in 30-day implied vol, and full
    rows (implied vol, skew, term structure, variance premium, 21-day forecast) for any tickers asked for."""
    s = store.load_json("vol", "summary")
    ov = store.load_frame("vol", "overview")
    if not s or ov is None:
        return {"error": "no vol data published"}
    out = {"as_of": s["as_of"], "last_health_check_ok": (s.get("last_health") or {}).get("ok")}
    m = store.load_frame("vol", "market")
    if m is not None and len(m) > 5:
        out["indices"] = {c.removeprefix("mkt_").upper(): {"now": m[c].iloc[-1], "5d_change": m[c].iloc[-1] - m[c].iloc[-6]}
                          for c in m.columns if m[c].notna().iloc[-6:].all()}
    pts = ov.set_index("ticker")
    chg = (pts["atm_30d_d5"] * 100).dropna().sort_values()
    out["biggest_5d_rises_30d_iv_pts"] = chg.tail(5)[::-1].to_dict()
    out["biggest_5d_falls_30d_iv_pts"] = chg.head(5).to_dict()
    cols = {"atm_30d": "iv_30d", "atm_30d_pct252": "iv_30d_1y_pctile", "rr25_30d": "risk_reversal_25d",
            "ts_30_91": "slope_30_to_91d", "vrp_30d": "variance_premium", "fc21_vol": "forecast_21d_vol",
            "earn_days_to": "earnings_in_days"}
    want = [t.upper() for t in (tickers or ["SPY", "QQQ", "IWM", "TLT", "HYG"]) if t.upper() in pts.index]
    rows = {}
    for t in want:
        r = pts.loc[t]
        rows[t] = {name: (r[c] * 100 if c in ("atm_30d", "rr25_30d", "ts_30_91", "vrp_30d", "fc21_vol")
                          and pd.notna(r[c]) else r[c]) for c, name in cols.items() if c in r}
    out["tickers_vol_pts"] = rows
    out["notes"] = ("Vol in vol points. Risk reversal = 25-delta call minus put (negative = puts richer). "
                    "Slope = 91d minus 30d ATM (negative = inverted). Variance premium = 30d implied minus 21d "
                    "realised.")
    return _r(out)


def tail_risk_overview() -> dict:
    """Simulated 21-day VaR/CVaR for the configured portfolio vs the same measures from history, hedges,
    CVaR-optimal weights and the crisis-regime probability."""
    s = store.load_json("tailrisk", "summary")
    if not s:
        return {"error": "no tail-risk data published"}
    return _r({k: s.get(k) for k in ("data_through", "portfolio", "simulated", "historical", "hedges",
                                     "optimal", "crisis_regime")}, 4)


def lookalikes() -> dict:
    """Today's closest historical market states and what followed, plus the method's own walk-forward
    track record (it has NOT shown skill on direction)."""
    s = store.load_json("analogs", "summary")
    if not s:
        return {"error": "no look-alike data published"}
    return _r({"as_of": s["as_of"], "closeness_vs_past_matches": s.get("closeness"),
               "today_features": [{k: f[k] for k in ("label", "value", "percentile", "analog_median")}
                                  for f in s["features"]],
               "episodes": [{k: a[k] for k in ("date", "distance", "ret_21", "ret_63", "vol_21", "mdd_21")}
                            for a in s["analogs"]],
               "outcomes_vs_all_days": s["outcomes"], "walk_forward_check": s.get("check")})


_SERIES = {
    "spy": ("market", "long_history", "spy"),
    "vix": ("market", "long_history", "vix"),
    "fear_greed": ("market", "gauge_history", "fear_greed"),
    "technical": ("market", "long_history", "technical"),
    "liquidity": ("market", "long_history", "liquidity"),
    "yield_curve_10y3m": ("market", "long_history", "t10y3m"),
    "economic": ("market", "econ_history", "economic"),
    "pct_above_50d": ("market", "breadth", "above_50"),
    "hy_spread_pts": ("credit", "spreads", "hy_oas"),
    "baa_spread_bps": ("credit", "spreads_bps", "baa_spread"),
    "credit_stress_prob": ("credit", "stress", "stress_prob"),
    "macro_p_recession": ("macro", "walk_forward", "p_recession"),
}


def series_history(name: str, years: float = 2.0) -> dict:
    """A published time series, sampled to about 60 points over the last `years`, with its latest value,
    range and where today sits in the full history."""
    if name not in _SERIES:
        return {"error": f"unknown series '{name}'", "available": sorted(_SERIES)}
    module, table, col = _SERIES[name]
    df = store.load_frame(module, table)
    if df is None or col not in df:
        return {"error": f"{module}/{table} has no '{col}'"}
    full = df[col].dropna()
    s = full[full.index >= full.index.max() - pd.DateOffset(days=int(365.25 * years))]
    step = max(1, len(s) // 60)
    sampled = s.iloc[::-step][::-1]
    return _r({"series": name, "latest": {"date": s.index[-1], "value": s.iloc[-1]},
               "window": {"min": s.min(), "max": s.max(), "start": s.index[0]},
               "full_history": {"since": full.index[0], "latest_percentile": (full <= full.iloc[-1]).mean()},
               "points": {d.strftime("%Y-%m-%d"): v for d, v in sampled.items()}}, 3)


TOOLS = [data_freshness, market_overview, gauge_detail, credit_overview, macro_overview, vol_overview,
         tail_risk_overview, lookalikes, series_history]
