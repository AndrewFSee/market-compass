"""Look-alike job: reads what the market and credit modules published, finds today's
historical look-alikes and checks the method walk-forward. Runs after "market"."""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from core import store
from modules.analogs import config as cfg
from modules.analogs import engine


def run(demo: bool = False, log=print) -> dict:
    long = store.load_frame("market", "long_history")
    if long is None or long.empty:
        raise RuntimeError("market/long_history not found: run the market job first")
    spreads = store.load_frame("credit", "spreads")
    hy = spreads["hy_oas"] if spreads is not None and "hy_oas" in spreads else None
    if hy is None:
        log("  no credit/spreads: look-alikes will be found without the high-yield features")

    state = engine.build_state(long, hy, cfg.FEATURES)
    out = engine.outcomes(long["spy"])
    weights = {k: v["weight"] for k, v in cfg.FEATURES.items()}
    today = state.index[-1]
    analogs, used = engine.find_analogs(state, today, weights, cfg.N_ANALOGS, cfg.SEPARATION_DAYS,
                                        cfg.PATH_DAYS, cfg.MIN_FEATURES)
    log(f"  {len(analogs)} look-alikes for {today:%Y-%m-%d} on {len(used)} features "
        f"({len(state.dropna(thresh=cfg.MIN_FEATURES))} comparable days since "
        f"{state.dropna(thresh=cfg.MIN_FEATURES).index[0]:%Y-%m-%d})")

    log("  checking the method walk-forward...")
    check = engine.evaluate(state, out, weights, cfg.N_ANALOGS, cfg.SEPARATION_DAYS, cfg.MIN_FEATURES,
                            cfg.EVAL_START_YEARS, cfg.EVAL_STEP_DAYS)
    distances = check.pop("distances", [])
    closeness = (float(np.mean(np.array(distances) >= analogs.mean())) if distances and len(analogs)
                 else None)  # share of past test dates whose look-alikes were further away

    # today's state with context
    hist = state.dropna(how="all")
    features = []
    for key, spec in cfg.FEATURES.items():
        if key not in state:
            continue
        s = hist[key].dropna()
        now = s.iloc[-1] if len(s) and s.index[-1] == today else np.nan
        features.append({"key": key, "label": spec["label"], "fmt": spec["fmt"], "used": key in used,
                         "value": None if pd.isna(now) else float(now),
                         "percentile": None if pd.isna(now) else float((s <= now).mean()),
                         "analog_median": float(state.loc[analogs.index, key].median()) if len(analogs) else None})

    rows = []
    for d, dist in analogs.items():
        o = out.loc[d]
        rows.append({"date": d.strftime("%Y-%m-%d"), "distance": dist,
                     **{c: (None if pd.isna(o[c]) else float(o[c])) for c in ("ret_21", "ret_63", "vol_21", "mdd_21")},
                     **{f"f_{k}": (None if pd.isna(state.at[d, k]) else float(state.at[d, k])) for k in state.columns}})

    known = out.loc[: out["ret_63"].last_valid_index()]
    summary = {
        "as_of": today.strftime("%Y-%m-%d"),
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "demo": demo,
        "features": features,
        "analogs": rows,
        "closeness": closeness,
        "history_start": hist.dropna(thresh=cfg.MIN_FEATURES).index[0].strftime("%Y-%m-%d"),
        "outcomes": {c: {"analogs": engine.describe(out.loc[analogs.index, c]), "all": engine.describe(known[c])}
                     for c in ("ret_21", "ret_63", "vol_21", "mdd_21")},
        "trailing_vol": None if pd.isna(out["trail_vol"].iloc[-1]) else float(out["trail_vol"].iloc[-1]),
        "check": check,
    }
    store.save_json(cfg.MODULE, "summary", summary)
    store.save_frame(cfg.MODULE, "paths", engine.paths(long["spy"], analogs.index, cfg.PATH_DAYS))
    o = summary["outcomes"]["ret_21"]["analogs"]
    if o["n"]:
        log(f"Look-alikes saved: median next month {o['median']:+.1f}% (all days "
            f"{summary['outcomes']['ret_21']['all']['median']:+.1f}%), walk-forward n={check.get('n')}")
    return summary
