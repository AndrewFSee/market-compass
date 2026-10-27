"""Look-alike engine: find past dates whose market state resembled a given date, and what
followed them. Pure pandas, no I/O, so it stays testable."""
from __future__ import annotations

import numpy as np
import pandas as pd

from modules.market.indicators import align


def build_state(long: pd.DataFrame, hy: pd.Series | None, features: dict) -> pd.DataFrame:
    """Daily market-state features on the S&P 500 calendar, each shifted by its publication lag.

    long: the market module's long_history (spy, vix, liquidity, t10y3m); hy: HY OAS in % pts."""
    spy = long["spy"].dropna()
    idx = spy.index
    vix = long["vix"].reindex(idx) if "vix" in long else pd.Series(np.nan, index=idx)
    raw = {
        "trend": (spy / spy.rolling(200).mean() - 1) * 100,
        "momentum": (spy / spy.shift(21) - 1) * 100,
        "vix": vix,
        "vix_trend": (vix / vix.rolling(50).mean() - 1) * 100,
    }
    if "liquidity" in long:
        raw["liquidity"] = long["liquidity"].reindex(idx)
    if "t10y3m" in long:
        raw["curve"] = long["t10y3m"].reindex(idx)
    h = align(hy, idx, limit=5) if hy is not None else None
    if h is not None:
        raw["hy"] = h
        raw["hy_chg"] = h - h.shift(63)
    cols = {k: raw[k].shift(spec["lag"]) for k, spec in features.items() if k in raw and raw[k].notna().any()}
    return pd.DataFrame(cols, index=idx).astype(float)


def outcomes(spy: pd.Series) -> pd.DataFrame:
    """What followed each date: S&P 500 return over 1 and 3 months (%), realised volatility over
    the next month (annualised %), worst close vs today within the next month (%), plus the
    trailing month's volatility (the naive forecast to beat)."""
    spy = spy.dropna()
    r = np.log(spy).diff()
    return pd.DataFrame({
        "ret_21": (spy.shift(-21) / spy - 1) * 100,
        "ret_63": (spy.shift(-63) / spy - 1) * 100,
        "vol_21": r.rolling(21).std().shift(-21) * np.sqrt(252) * 100,
        "mdd_21": (spy.rolling(21).min().shift(-21) / spy - 1).clip(upper=0) * 100,
        "trail_vol": r.rolling(21).std() * np.sqrt(252) * 100,
    })


def find_analogs(state: pd.DataFrame, at, weights: dict, k: int, separation: int, min_gap: int,
                 min_features: int) -> tuple[pd.Series, list[str]]:
    """The `k` dates most like `at`, at least `separation` rows apart, using only data up to `at`.

    Features are z-scored on their history up to `at`; distance is the weighted RMS gap over the
    features both dates have. Candidates end `min_gap` rows before `at` so their outcomes are known.
    Returns (distance by analog date, the features used)."""
    hist = state.loc[:at]
    target = hist.iloc[-1]
    used = [c for c in hist.columns if pd.notna(target[c]) and weights.get(c, 0) > 0]
    if not used or len(hist) <= min_gap:
        return pd.Series(dtype=float), used
    sd = hist[used].std().replace(0, np.nan)
    z = (hist[used] - hist[used].mean()) / sd
    cand = z.iloc[: len(z) - min_gap]
    w = pd.Series({c: weights[c] for c in used})
    present = cand.notna()
    enough = present.sum(axis=1) >= min(min_features, len(used))
    sq = (cand - z.iloc[-1]).pow(2).mul(w, axis=1)
    dist = np.sqrt(sq.sum(axis=1, min_count=1) / present.mul(w, axis=1).sum(axis=1))
    dist = dist[enough].dropna().sort_values()

    pos = z.index.get_indexer(dist.index)
    taken = np.zeros(len(z), dtype=bool)
    chosen = []
    for d, v, p in zip(dist.index, dist.values, pos):
        if taken[p]:
            continue
        chosen.append((d, float(v)))
        taken[max(0, p - separation): p + separation + 1] = True
        if len(chosen) == k:
            break
    return pd.Series(dict(chosen), dtype=float), used


def describe(values: pd.Series) -> dict:
    v = values.dropna()
    if v.empty:
        return {"median": None, "p10": None, "p90": None, "share_up": None, "n": 0}
    return {"median": float(v.median()), "p10": float(v.quantile(0.1)), "p90": float(v.quantile(0.9)),
            "share_up": float((v > 0).mean()), "n": int(len(v))}


def paths(spy: pd.Series, dates, days: int) -> pd.DataFrame:
    """S&P 500 rebased to 100 on each date, for the next `days` sessions (rows 0..days)."""
    spy = spy.dropna()
    out = {}
    for d in dates:
        p = spy.index.get_loc(d)
        seg = spy.iloc[p: p + days + 1]
        out[pd.Timestamp(d).strftime("%Y-%m-%d")] = pd.Series(seg.values / seg.iloc[0] * 100,
                                                              index=range(len(seg)))
    return pd.DataFrame(out).reindex(range(days + 1))


def rank_corr(a: pd.Series, b: pd.Series) -> float:
    return float(a.rank().corr(b.rank()))


def evaluate(state: pd.DataFrame, out: pd.DataFrame, weights: dict, k: int, separation: int,
             min_features: int, start_years: int, step: int, horizon: int = 21) -> dict:
    """Walk-forward check: every `step` sessions, find look-alikes using only the past and compare
    their median next-month outcome with what actually happened. Non-overlapping test months."""
    first = state.dropna(thresh=min_features).index
    if first.empty:
        return {"n": 0}
    dates = state.index[state.index >= first[0] + pd.DateOffset(years=start_years)]
    tests = dates[: max(0, len(dates) - horizon)][::step]
    rows = []
    for t in tests:
        an, _ = find_analogs(state, t, weights, k, separation, horizon, min_features)
        if len(an) < max(3, k // 2):
            continue
        o = out.loc[an.index]
        rows.append({"date": t, "pred_ret": o["ret_21"].median(), "pred_vol": o["vol_21"].median(),
                     "naive_vol": out.at[t, "trail_vol"], "real_ret": out.at[t, "ret_21"],
                     "real_vol": out.at[t, "vol_21"], "distance": float(an.mean())})
    df = pd.DataFrame(rows).dropna()
    n = len(df)
    if n < 24:
        return {"n": n}

    def sig(rho):
        return bool(abs(rho) * np.sqrt(n - 1) > 1.96)

    ic_ret, ic_vol, ic_naive = (rank_corr(df["pred_ret"], df["real_ret"]),
                                rank_corr(df["pred_vol"], df["real_vol"]),
                                rank_corr(df["naive_vol"], df["real_vol"]))
    # does the look-alike vol forecast add anything to "last month's vol continues"?
    resid = df["real_vol"].rank() - df["naive_vol"].rank() * np.corrcoef(df["naive_vol"].rank(),
                                                                          df["real_vol"].rank())[0, 1]
    ic_vol_extra = rank_corr(df["pred_vol"], resid)
    return {"n": n, "start": df["date"].iloc[0].strftime("%Y-%m-%d"),
            "ic_return": ic_ret, "sig_return": sig(ic_ret),
            "ic_vol": ic_vol, "sig_vol": sig(ic_vol), "ic_vol_naive": ic_naive,
            "ic_vol_extra": ic_vol_extra, "sig_vol_extra": sig(ic_vol_extra),
            "distances": df["distance"].tolist()}
