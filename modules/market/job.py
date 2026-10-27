"""Market data job: pull inputs, compute every indicator, save results for the page.

Run through the hub runner:   python run_jobs.py            (real data)
                              python run_jobs.py --demo     (synthetic data)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from core import store
from modules.market import config as cfg
from modules.market import indicators as ind

MODULE = cfg.MODULE
CAP_REFRESH_DAYS = 7


# ----------------------------------------------------------------- inputs
def _apply_credit_override(fred: dict, log) -> None:
    o = cfg.CREDIT_OVERRIDE
    if not o:
        return
    df = store.load_frame(o["module"], o["name"])
    if df is None:
        log(f"  credit override: {o['module']}/{o['name']} not found, using FRED spreads")
        return
    df.index = pd.to_datetime(df.index)
    fred[cfg.HY_OAS] = df[o["hy"]].astype(float)
    fred[cfg.IG_OAS] = df[o["ig"]].astype(float)
    log(f"  credit spreads taken from {o['module']}/{o['name']}")


def _market_caps(symbols: list[str], log) -> pd.Series:
    from modules.market import sources

    cached = store.load_frame(MODULE, "market_caps")
    now = datetime.now(timezone.utc).isoformat()
    if cached is not None and len(cached):
        fresh = cached[pd.to_datetime(cached["fetched"]) > datetime.now(timezone.utc) - timedelta(days=CAP_REFRESH_DAYS)]
        missing = [s for s in symbols if s not in fresh.index or pd.isna(fresh.at[s, "market_cap"])]
        if len(missing) < 0.1 * len(symbols):
            if missing:  # e.g. new index members: top up just those
                extra = sources.fetch_market_caps(missing, log).to_frame().assign(fetched=now)
                fresh = pd.concat([fresh.drop(index=missing, errors="ignore"), extra])
                store.save_frame(MODULE, "market_caps", fresh)
            else:
                log("  market caps: using cached values")
            return fresh["market_cap"]
    caps = sources.fetch_market_caps(symbols, log)
    store.save_frame(MODULE, "market_caps", caps.to_frame().assign(fetched=now))
    return caps


def fetch_inputs(log=print) -> dict:
    from modules.market import sources

    log("Fetching FRED series...")
    fred, missing = sources.fetch_fred_many(cfg.all_fred_ids(), log)
    _apply_credit_override(fred, log)
    log("Fetching ETF prices...")
    etf = sources.download_closes(cfg.all_etf_tickers(), cfg.PRICE_PERIOD, log=log)
    long = sources.download_closes([cfg.BENCHMARK], cfg.BENCHMARK_LONG_PERIOD, log=log)
    spy_long = long[cfg.BENCHMARK] if cfg.BENCHMARK in long else None
    log("Fetching index members...")
    cons = sources.fetch_constituents(log)
    log("Fetching stock prices (this takes a minute or two)...")
    stocks = sources.download_closes(cons["yf_symbol"].tolist(), cfg.PRICE_PERIOD, log=log)
    caps = _market_caps(cons["yf_symbol"].tolist(), log)
    missing += [t for t in cfg.all_etf_tickers() if t not in etf.columns]
    return {"fred": fred, "etf": etf, "spy_long": spy_long, "constituents": cons, "stocks": stocks,
            "caps": caps, "missing": missing, "demo": False}


# ----------------------------------------------------------------- outputs
def _f(x):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) or pd.isna(x) else float(x)


def _summary(key: str, comp: ind.Composite, at=None, weights: dict | None = None,
             market: pd.Series | None = None) -> dict:
    """Latest reading, components, trend vs earlier readings and the link to `market`."""
    spec = cfg.GAUGES[key]
    s = comp.value.dropna()
    base = {"title": spec["title"], "lo": spec["lo"], "hi": spec["hi"], "cuts": spec["cuts"],
            "colors": spec["colors"], "caption": spec["caption"]}
    if s.empty:
        return {**base, "value": None, "label": cfg.gauge_label(key, None), "date": None, "components": []}
    date = at if at is not None and at in s.index else s.index[-1]
    value = float(s.loc[date])
    components = []
    for c in comp.scores.columns:
        raw = comp.raw[c].loc[:date].dropna() if c in comp.raw else pd.Series(dtype=float)
        sc = comp.scores[c].loc[:date].dropna()
        row = {"component": c,
               "reading": _f(raw.iloc[-1]) if len(raw) else None,
               "score": _f(sc.iloc[-1]) if len(sc) else None,
               "as_of": raw.index[-1].strftime("%Y-%m-%d") if len(raw) else None}
        if weights is not None:
            total = sum(weights.values()) or 1
            row["weight"] = weights.get(c, 0) / total
        components.append(row)
    horizon, horizon_label = cfg.GAUGE_HORIZON[key]
    link = (ind.market_link(s.loc[:date], market, horizon, spec["cuts"], lag=cfg.GAUGE_PUBLICATION_LAG[key])
            if market is not None else {})
    return {**base, "value": value, "label": cfg.gauge_label(key, value),
            "date": date.strftime("%Y-%m-%d"), "components": components,
            "trend": ind.changes(s, date, cfg.GAUGE_TREND[key]),
            "vs_spy": {**link, "horizon_label": horizon_label} if link else None}


def last_complete_session(etf: pd.DataFrame, stocks: pd.DataFrame, min_coverage: float = 0.9) -> pd.Timestamp:
    """Latest date with a benchmark close and prices for most stocks.

    Yahoo sometimes serves today's row half-filled (e.g. VIX but not SPY, or only some
    stocks); computing on it would mix sessions in breadth and returns."""
    last = etf[cfg.BENCHMARK].dropna().index[-1]
    if not stocks.empty:
        counts = stocks.notna().sum(axis=1)
        full = counts[counts >= min_coverage * counts.tail(20).max()]
        if len(full):
            last = min(last, full.index[-1])
    return last


def build(inputs: dict, log=print) -> dict:
    fred, etf, stocks, cons = inputs["fred"], inputs["etf"], inputs["stocks"], inputs["constituents"]
    if cfg.BENCHMARK not in etf:
        raise RuntimeError(f"No prices for {cfg.BENCHMARK}; cannot build the market page")
    session = last_complete_session(etf, stocks)
    if etf.index[-1] > session or (not stocks.empty and stocks.index[-1] > session):
        log(f"  dropping incomplete price rows after {session:%Y-%m-%d}")
    etf, stocks = etf.loc[:session], stocks.loc[:session]
    spy = etf[cfg.BENCHMARK].dropna()
    # full benchmark history (demo data has none: fall back to the ETF window)
    spy_long = inputs.get("spy_long")
    spy_long = spy if spy_long is None or spy_long.dropna().empty else spy_long.dropna().loc[:session]
    spy_monthly = spy_long.resample("MS").last()  # month-start label, month-end close (econ calendar)

    log("Computing breadth...")
    sp_cols = [c for c in cons.loc[cons["sp500"], "yf_symbol"] if c in stocks.columns]
    breadth = ind.breadth(stocks[sp_cols]) if sp_cols else pd.DataFrame()

    log("Computing gauges...")
    fg = ind.fear_greed(spy, etf.get(cfg.VIX), etf.get(cfg.SAFE_HAVEN),
                        fred.get(cfg.HY_OAS), fred.get(cfg.IG_OAS), breadth)
    tech = ind.technical(spy_long)  # trailing windows only, so recent values match a 5-year fit
    liq = ind.liquidity(fred, cfg.LIQUIDITY_FACTORS, tuple(cfg.NETLIQ_PARTS))
    econ = ind.economic(fred, cfg.ECON_INDICATORS, cfg.GDP_SERIES, cfg.ECON_LEAD_MONTHS,
                        coverage_threshold=cfg.ECON_COVERAGE_THRESHOLD)

    gauges = {
        "fear_greed": _summary("fear_greed", fg, market=spy),
        "liquidity": _summary("liquidity", liq, market=spy_long),
        "technical": _summary("technical", tech, market=spy_long),
        "economic": _summary("economic", econ, at=econ.extra.get("as_of"), weights=econ.extra.get("weights"),
                             market=spy_monthly),
    }
    e = gauges["economic"]
    if e["value"] is not None:
        as_of = econ.extra["as_of"]
        text = (f"As of {as_of:%b %Y}. Composite of {econ.extra['n']} leading indicators, weighted by "
                f"their fit to GDP growth {cfg.ECON_LEAD_MONTHS} months ahead. Higher = expanding, "
                f"lower = contracting.")
        if econ.extra.get("provisional") is not None:
            text += (f" {econ.extra['provisional']:%b %Y} provisional "
                     f"({econ.extra['provisional_coverage']:.0%} of indicators reported).")
        e["caption"] = text

    history = pd.concat({"fear_greed": fg.value, "technical": tech.value,
                         "liquidity": liq.value.reindex(spy.index.union(liq.value.index))}, axis=1, sort=True)
    history = history.loc[history.index >= spy.index[0]].dropna(how="all")
    history["spy"] = spy.reindex(history.index)
    econ_history = pd.DataFrame({"economic": econ.value, "coverage": econ.extra.get("coverage")})
    econ_history["spy"] = spy_monthly.reindex(econ_history.index)

    log("Computing returns...")
    etf_returns = ind.period_returns(etf.drop(columns=[cfg.VIX], errors="ignore"), cfg.TIMEFRAMES)
    stock_returns = ind.period_returns(stocks, cfg.TIMEFRAMES)
    caps = inputs["caps"].rename("market_cap")
    cons_perf = (cons.set_index("yf_symbol")
                 .join(caps, how="left")
                 .join(stock_returns.drop(columns=["date"], errors="ignore"), how="left")
                 .reset_index())

    now = datetime.now()
    meta = {
        "run_at": now.isoformat(timespec="seconds"),
        "run_at_local": now.strftime("%b %d, %Y %I:%M %p"),
        "as_of": spy.index[-1].strftime("%b %d, %Y"),
        "demo": bool(inputs.get("demo")),
        "missing": sorted(set(inputs.get("missing", []))),
        "counts": {"etfs": int(etf.shape[1]), "stocks": int(stocks.shape[1]), "fred": len(fred)},
    }
    return {"gauges": gauges, "gauge_history": history, "econ_history": econ_history,
            "breadth": breadth, "etf_returns": etf_returns, "constituents_perf": cons_perf, "meta": meta}


def save(outputs: dict) -> None:
    for name, obj in outputs.items():
        if isinstance(obj, pd.DataFrame):
            store.save_frame(MODULE, name, obj)
        else:
            store.save_json(MODULE, name, obj)


def run(demo: bool = False, log=print) -> dict:
    if demo:
        from modules.market import demo as demo_data
        inputs = demo_data.generate()
    else:
        inputs = fetch_inputs(log)
    outputs = build(inputs, log)
    save(outputs)
    log(f"Market data saved (through {outputs['meta']['as_of']}).")
    return outputs["meta"]
