"""Growth vs value job: downloads Ken French's 2x3 portfolios (monthly, since 1926), builds the value
spread and the investment / profitability gaps between large growth and large value, backtests the
investment-gap rule (on time and acted on late, on French's portfolios and on growth / value ETFs) and
puts TickerLake's SEC-based gaps (`style/gaps`, when the style job has run) on French's scale.

Writes data/growth_value/: history (monthly panel + rule positions + rule returns), annual (one row per
July), live (SEC-based gaps by month with French's alongside), summary.json.
"""
from __future__ import annotations

import io
import zipfile

import numpy as np
import pandas as pd

from core import store
from modules.growth_value import calc, demo as demo_data
from modules.growth_value import config as cfg


def fetch_french(log=print) -> str:
    from modules.market.sources import HEADERS
    import requests
    r = requests.get(cfg.FRENCH_URL, headers=HEADERS, timeout=60)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        text = z.read(name).decode("latin-1")
    log(f"  French 6 portfolios: {len(text) / 1e6:.1f} MB ({name})")
    return text


def etf_monthly(closes: pd.DataFrame) -> pd.DataFrame:
    return closes.resample("ME").last().pct_change()


def run(demo: bool = False, log=print) -> dict:
    text = demo_data.french_text() if demo else fetch_french(log)
    secs = calc.parse_sections(text)
    p = calc.panel(secs, cfg.GROWTH, cfg.VALUE, cfg.SECTIONS, cfg.Z_MIN_MONTHS)
    last = p["ret_g"].dropna().index[-1]
    p = p.loc[:last]
    state = calc.rule_state(p["z_inv"], cfg.THRESHOLD)
    log(f"  French data through {last:%Y-%m}; investment-gap z {p['z_inv'].iloc[-1]:+.2f} -> {state.iloc[-1]}")

    # ---- backtests on French's portfolios
    bts = {lag: calc.backtest(state, p["ret_g"], p["ret_v"], cfg.COST, lag) for lag in cfg.LAGS}
    yearly = calc.backtest(calc.once_a_year(state), p["ret_g"], p["ret_v"], cfg.COST, cfg.REALISTIC_LAG)
    periods = [(a, b) for a, b in cfg.PERIODS]
    rule = {str(lag): [calc.summarize(bt, a, b) for a, b in periods] for lag, bt in bts.items()}
    rule["yearly"] = [calc.summarize(yearly, a, b) for a, b in periods]
    # the same rule on the other two readings, for context
    others = {}
    for key, z in (("op", -p["z_op"]), ("vs", p["z_vs"])):       # profitability: growth when its gap is high
        bt = calc.backtest(calc.rule_state(z, 0.0), p["ret_g"], p["ret_v"], cfg.COST)
        others[key] = [calc.summarize(bt, a, b) for a, b in periods]

    # ---- one reading per July
    a = calc.annual(p)
    annual_tests = {k: {"all": calc.annual_test(a, col), "first": calc.annual_test(a, col, end=1999),
                        "second": calc.annual_test(a, col, start=2000)}
                    for k, col in (("inv", "z_inv"), ("op", "z_op"), ("vs", "z_vs"))}
    annual_tests["inv"]["no_bubble"] = calc.annual_test(a, "z_inv", drop=cfg.EXCLUDE_BUBBLE)
    decades = calc.by_decade(a, "z_inv")

    # ---- ETFs: French-based position applied to growth / value ETFs
    try:
        closes = demo_data.etf_closes() if demo else _etf_closes(log)
        em = etf_monthly(closes)
        etf = []
        for g, v, start in cfg.ETF_PAIRS:
            if g in em and v in em:
                for lag in (0, cfg.REALISTIC_LAG):
                    bt = calc.backtest(state, em[g].loc[start:], em[v].loc[start:], cfg.COST, lag)
                    etf.append({"pair": f"{g}/{v}", "lag": lag, **calc.summarize(bt)})
    except Exception as e:  # noqa: BLE001 - the ETF check is context, not the signal
        log(f"  ETF check skipped ({e})")
        etf = []

    # ---- live: TickerLake's SEC-based gaps on French's scale
    live_out, live_frame = {"available": False}, None
    gaps = store.load_frame("style", "gaps")
    if gaps is not None and len(gaps):
        gm = calc.to_month(gaps)
        cal = calc.calibrate(p["inv_gap"], gm["ag_gap"], cfg.LIVE_LEAD_MONTHS)
        latest = gaps.sort_values("date").iloc[-1]
        reading = calc.live_reading(cal, float(latest["ag_gap"]), p["inv_gap"], cfg.THRESHOLD, cfg.LIVE_MIN_CORR,
                                    cfg.LIVE_MIN_MONTHS)
        live_out = {"available": True, "as_of": str(pd.Timestamp(latest["date"]).date()),
                    "ag_gap": float(latest["ag_gap"]), "growth_ag": float(latest["growth_ag"]),
                    "value_ag": float(latest["value_ag"]), "roe_gap": float(latest["roe_gap"]),
                    "value_spread": float(latest["value_spread"]), "growth_n": int(latest["growth_n"]),
                    "value_n": int(latest["value_n"]),
                    "cover": float(min(latest["growth_ag_cover"], latest["value_ag_cover"])),
                    "calibration": cal, **reading,
                    "corr_same_month": calc.calibrate(p["inv_gap"], gm["ag_gap"]).get("corr"),
                    "corr_growth_side": calc.calibrate(p["inv_g"], gm["growth_ag"], cfg.LIVE_LEAD_MONTHS).get("corr"),
                    "corr_value_side": calc.calibrate(p["inv_v"], gm["value_ag"], cfg.LIVE_LEAD_MONTHS).get("corr")}
        live_frame = gm[["ag_gap", "growth_ag", "value_ag", "roe_gap", "value_spread"]].join(
            p[["inv_gap", "op_gap", "value_spread"]].rename(columns=lambda c: f"french_{c}"), how="left")
        ahead = p["inv_gap"].copy()
        ahead.index = ahead.index - pd.offsets.MonthEnd(cfg.LIVE_LEAD_MONTHS)
        live_frame["french_inv_gap_ahead"] = ahead.reindex(live_frame.index)
        if "slope" in cal:
            f = p["inv_gap"].dropna()
            live_frame["z_mapped"] = (cal["intercept"] + cal["slope"] * live_frame["ag_gap"] - f.mean()) / f.std()
        log(f"  live (SEC) gap {live_out['ag_gap']:+.3f} on {live_out['as_of']}, corr with French "
            f"{cal.get('corr', float('nan')):+.2f} over {cal.get('n', 0)} months -> "
            f"{reading.get('signal', 'n/a')}{'' if reading['tracking'] else ' (loose: ' + str(reading['reason']) + ')'}")
    else:
        log("  no style/gaps yet: run the style job (TickerLake) for the live reading")

    # ---- save
    hist = p.copy()
    hist["position"] = state
    hist["rule_ret"] = bts[0]["rot"]
    hist["rule_late_ret"] = bts[cfg.REALISTIC_LAG]["rot"]
    hist["blend_ret"] = bts[0]["blend"]
    store.save_frame(cfg.MODULE, "history", hist.reset_index(names="date"))
    store.save_frame(cfg.MODULE, "annual", a.reset_index())
    if live_frame is not None:
        store.save_frame(cfg.MODULE, "live", live_frame.reset_index(names="month"))
    now = p.iloc[-1]
    summary = {
        "as_of": str(last.date()), "data_through": calc.data_through(text), "demo": demo,
        "now": {"z_inv": now["z_inv"], "inv_gap": now["inv_gap"], "inv_g": now["inv_g"], "inv_v": now["inv_v"],
                "z_op": now["z_op"], "op_gap": now["op_gap"], "z_vs": now["z_vs"], "value_spread": now["value_spread"],
                "signal": "value" if state.iloc[-1] == "V" else "growth",
                "since": str(_since(state).date())},
        "rule": rule, "others": others, "periods": [[a_, b_] for a_, b_ in periods], "lags": list(cfg.LAGS),
        "annual": annual_tests, "decades": decades, "etf": etf, "live": live_out,
        "settings": {"threshold": cfg.THRESHOLD, "cost_bp": cfg.COST * 1e4, "z_min_months": cfg.Z_MIN_MONTHS,
                     "realistic_lag": cfg.REALISTIC_LAG, "tries": cfg.TRIES},
    }
    store.save_json(cfg.MODULE, "summary", summary)
    on, late = rule["0"][-1], rule[str(cfg.REALISTIC_LAG)][-1]
    log(f"  rule {on.get('start', '')[:4]}-{last:%Y}: {on.get('excess', float('nan')):+.2f}%/yr (t {on.get('t', float('nan')):.2f}) "
        f"on time, {late.get('excess', float('nan')):+.2f} (t {late.get('t', float('nan')):.2f}) {cfg.REALISTIC_LAG} months late")
    return summary


def _since(state: pd.Series) -> pd.Timestamp:
    s = state.dropna()
    changed = s.index[s != s.shift(1)]
    return changed[-1] if len(changed) else s.index[0]


def _etf_closes(log) -> pd.DataFrame:
    from modules.market.sources import download_closes
    tickers = sorted({t for g, v, _ in cfg.ETF_PAIRS for t in (g, v)})
    return download_closes(tickers, period="max", log=log)


if __name__ == "__main__":
    import sys
    run(demo="--demo" in sys.argv)
