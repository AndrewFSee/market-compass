"""Pure calculations - no network, no Streamlit. Easy to test and to tweak."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class Composite:
    value: pd.Series                      # the gauge reading over time
    raw: pd.DataFrame                     # each component's underlying reading
    scores: pd.DataFrame                  # each component on the gauge's scale
    extra: dict = field(default_factory=dict)


# ----------------------------------------------------------------- helpers
def pct(s: pd.Series, n: int) -> pd.Series:
    return s.pct_change(n, fill_method=None) * 100


def rolling_percentile(s: pd.Series, window: int = 504, min_periods: int = 126) -> pd.Series:
    """Where today's value sits within its trailing window, 0-100."""
    return s.rolling(window, min_periods=min_periods).rank(pct=True) * 100


def rolling_z(s: pd.Series, window: int, min_periods: int) -> pd.Series:
    mean = s.rolling(window, min_periods=min_periods).mean()
    std = s.rolling(window, min_periods=min_periods).std()
    return (s - mean) / std.replace(0, np.nan)


def z_to_score(z, cap: float = 2.5):
    """Map a z-score to -100..+100 (capped at +/- cap standard deviations)."""
    return z.clip(-cap, cap) / cap * 100


def _clean_series(s: pd.Series | None) -> pd.Series | None:
    if s is None:
        return None
    s = s.dropna().sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return s if not s.empty else None


def align(s: pd.Series | None, index: pd.Index, limit: int = 10) -> pd.Series | None:
    """Put a series on another series' dates, carrying values forward briefly."""
    s = _clean_series(s)
    if s is None:
        return None
    return s.reindex(s.index.union(index)).ffill(limit=limit).reindex(index)


def combine(scores: pd.DataFrame, min_share: float = 0.5) -> pd.Series:
    """Average the component scores; require at least half of them to be present."""
    if scores.shape[1] == 0:
        return pd.Series(dtype=float, index=scores.index)
    need = max(1, int(np.ceil(scores.shape[1] * min_share)))
    return scores.mean(axis=1, skipna=True).where(scores.notna().sum(axis=1) >= need)


def to_business_daily(series: dict[str, pd.Series], limit: int = 10) -> pd.DataFrame:
    parts = {k: _clean_series(v) for k, v in series.items()}
    parts = {k: v for k, v in parts.items() if v is not None}
    if not parts:
        return pd.DataFrame()
    df = pd.concat(parts, axis=1, sort=True)
    return df.resample("B").last().ffill(limit=limit)


# ----------------------------------------------------------------- technicals
def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    out = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    return out.where(dn != 0, 100.0).where(up.notna())


def stochastic(close: pd.Series, n: int = 14, smooth: int = 3) -> pd.Series:
    lo = close.rolling(n).min()
    hi = close.rolling(n).max()
    k = (close - lo) / (hi - lo).replace(0, np.nan) * 100
    return k.rolling(smooth).mean()


def macd_hist(close: pd.Series) -> pd.Series:
    macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    signal = macd.ewm(span=9, adjust=False).mean()
    return (macd - signal) / close * 100  # as % of price so it is comparable over time


# ----------------------------------------------------------------- gauges
def _percentile_composite(parts: dict, index: pd.Index, window: int) -> Composite:
    """parts: name -> (series, sign, mode) where mode is 'pct' or 'direct'."""
    raw, scores = {}, {}
    for name, (s, sign, mode) in parts.items():
        if s is None or s.dropna().empty:
            continue
        raw[name] = s
        if mode == "direct":
            sc = s
        else:
            sc = rolling_percentile(s, window)
        scores[name] = sc if sign > 0 else 100 - sc
    raw_df = pd.DataFrame(raw, index=index)
    score_df = pd.DataFrame(scores, index=index)
    return Composite(combine(score_df), raw_df, score_df)


def fear_greed(spy, vix=None, bonds=None, hy=None, ig=None, breadth=None, window=504) -> Composite:
    """0-100 sentiment gauge. Each component is ranked against its own trailing two
    years, then averaged. (A put/call ratio component would slot in the same way if
    you have a source for it.)"""
    spy = _clean_series(spy)
    idx = spy.index
    parts = {"Momentum: S&P 500 vs 125-day avg (%)": ((spy / spy.rolling(125).mean() - 1) * 100, 1, "pct")}
    if breadth is not None and not breadth.empty:
        parts["Strength: net new 52-wk highs (% of stocks)"] = (align(breadth["net_highs_pct"], idx), 1, "pct")
        parts["Breadth: % of stocks above 50-day avg"] = (align(breadth["above_50"], idx), 1, "pct")
    v = align(vix, idx)
    if v is not None:
        parts["Volatility: VIX vs its 50-day avg (%)"] = ((v / v.rolling(50).mean() - 1) * 100, -1, "pct")
    b = align(bonds, idx)
    if b is not None:
        parts["Safe haven: stocks minus bonds, 20-day (%)"] = (pct(spy, 20) - pct(b, 20), 1, "pct")
    h, g = align(hy, idx), align(ig, idx)
    if h is not None and g is not None:
        parts["Junk demand: HY minus IG spread (pts)"] = (h - g, -1, "pct")
    return _percentile_composite(parts, idx, window)


def technical(spy, window=504) -> Composite:
    """0-100 overbought/oversold composite for the S&P 500."""
    spy = _clean_series(spy)
    idx = spy.index
    parts = {
        "RSI (14-day)": (rsi(spy), 1, "direct"),
        "Stochastic (14-day)": (stochastic(spy), 1, "direct"),
        "MACD histogram (% of price)": (macd_hist(spy), 1, "pct"),
        "Distance from 50-day avg (%)": ((spy / spy.rolling(50).mean() - 1) * 100, 1, "pct"),
        "Distance from 200-day avg (%)": ((spy / spy.rolling(200).mean() - 1) * 100, 1, "pct"),
    }
    return _percentile_composite(parts, idx, window)


def liquidity(fred: dict, factors: list[dict], netliq_parts=("WALCL", "WTREGEN", "RRPONTSYD"),
              window=756, min_periods=252) -> Composite:
    """-100..+100. Each factor is z-scored against its trailing ~3 years."""
    needed = set()
    for f in factors:
        needed.update(netliq_parts if f["series"] == "NETLIQ" else [f["series"]])
    df = to_business_daily({k: fred.get(k) for k in needed})
    if df.empty:
        return Composite(pd.Series(dtype=float), pd.DataFrame(), pd.DataFrame())
    if set(netliq_parts) <= set(df.columns):
        walcl, tga, rrp = (df[c] for c in netliq_parts)
        # WALCL and the TGA are in $ millions; overnight reverse repo is in $ billions
        df["NETLIQ"] = walcl - tga - rrp.fillna(0) * 1000
    raw, scores = {}, {}
    for f in factors:
        if f["series"] not in df.columns:
            continue
        s = df[f["series"]]
        t = {"level": s, "diff63": s.diff(63), "pct63": pct(s, 63)}[f["transform"]]
        raw[f["name"]] = t
        scores[f["name"]] = z_to_score(rolling_z(t, window, min_periods) * f["sign"])
    raw_df, score_df = pd.DataFrame(raw), pd.DataFrame(scores)
    return Composite(combine(score_df), raw_df, score_df)


def economic(fred: dict, specs: list[dict], gdp_id="GDPC1", lead=6, z_window=240, z_min=60,
             coverage_threshold=0.75) -> Composite:
    """-100..+100 composite of monthly leading indicators.

    Each indicator is transformed (6-month change etc.), z-scored over its trailing
    20 years, and weighted by its historical correlation with real GDP growth
    `lead` months later (indicators that have not helped get zero weight).
    Also reports how many indicators have reported for recent months, since
    monthly data trickles in over several weeks."""
    z, transformed, reported = {}, {}, {}
    for spec in specs:
        s = _clean_series(fred.get(spec["id"]))
        if s is None:
            continue
        m = s.resample("MS").mean()
        reported[spec["name"]] = m.notna()
        t = {"pct6": pct(m, 6), "diff6": m.diff(6), "level": m}[spec["transform"]]
        transformed[spec["name"]] = t
        z[spec["name"]] = rolling_z(t, z_window, z_min) * spec["sign"]
    if not z:
        return Composite(pd.Series(dtype=float), pd.DataFrame(), pd.DataFrame())
    Z = pd.DataFrame(z)
    T = pd.DataFrame(transformed).reindex(Z.index)
    R = pd.DataFrame(reported).reindex(Z.index).fillna(False).astype(bool)

    weights = dict.fromkeys(Z.columns, 0.0)
    gdp = _clean_series(fred.get(gdp_id))
    if gdp is not None:
        growth = pct(gdp, 4)  # year-over-year, quarterly data
        monthly = growth.resample("MS").ffill()
        target = monthly.reindex(Z.index).shift(-lead)
        for c in Z.columns:
            pair = pd.concat([Z[c], target], axis=1).dropna()
            if len(pair) >= 36:
                corr = pair.iloc[:, 0].corr(pair.iloc[:, 1])
                weights[c] = float(max(corr, 0.0)) if np.isfinite(corr) else 0.0
    if sum(weights.values()) == 0:
        weights = dict.fromkeys(Z.columns, 1.0)
    W = pd.Series(weights)

    S = z_to_score(Z)
    num = (S * W).sum(axis=1, min_count=1)
    den = (S.notna() * W).sum(axis=1)
    comp = num / den.replace(0, np.nan)
    coverage = R.sum(axis=1) / R.shape[1]

    final = coverage[(coverage >= coverage_threshold) & comp.notna()]
    as_of = final.index[-1] if len(final) else (comp.dropna().index[-1] if comp.notna().any() else None)
    provisional, prov_cov = None, None
    if as_of is not None:
        later = coverage[(coverage.index > as_of) & (coverage > 0)]
        if len(later):
            provisional, prov_cov = later.index[-1], float(later.iloc[-1])
    extra = {"weights": weights, "coverage": coverage, "as_of": as_of,
             "provisional": provisional, "provisional_coverage": prov_cov, "n": int(Z.shape[1])}
    return Composite(comp, T, S, extra)


# ----------------------------------------------------------------- trend & market link
def changes(value: pd.Series, at, lags: dict[str, int]) -> dict:
    """The reading `n` observations before `at` and the change since, for each label -> n."""
    s = _clean_series(value)
    if s is None:
        return {}
    s = s.loc[:at]
    out = {}
    for label, n in lags.items():
        if len(s) > n:
            prior = float(s.iloc[-1 - n])
            out[label] = {"prior": prior, "change": float(s.iloc[-1]) - prior,
                          "date": s.index[-1 - n].strftime("%Y-%m-%d")}
    return out


def market_link(gauge: pd.Series, price: pd.Series, horizon: int, cuts: list[float], lag: int = 0,
                min_obs: int = 24) -> dict:
    """How a gauge relates to the market, on the gauge's own calendar.

    * coincident: correlation of the gauge's change over `horizon` periods with the
      market's return over the same periods - does it move with the market?
    * predictive: rank correlation of the gauge's level with the market's return over
      the *next* `horizon` periods - does it say anything about what comes next?
      The reading is used `lag` periods after its date, when its inputs had actually
      been published; otherwise a gauge built on lagged data (FRED weekly/monthly
      series) gets credit for information nobody had yet.

    Both use non-overlapping periods (every `horizon`-th observation, anchored at the
    latest), so `n` counts independent periods and the significance check is honest:
    |rho| * sqrt(n - 1) > 1.96. `bands` gives the next-period return by gauge band,
    using every observation (overlapping, so `periods` = days / horizon is the
    effective sample size)."""
    g = _clean_series(gauge)
    p = _clean_series(price)
    if g is None or p is None:
        return {}
    df = pd.DataFrame({"g": g, "p": align(p, g.index)}).dropna()
    if len(df) <= 2 * horizon:
        return {}
    df["fwd"] = (df["p"].shift(-horizon) / df["p"] - 1) * 100
    df["past"] = (df["p"] / df["p"].shift(horizon) - 1) * 100
    df["dg"] = df["g"] - df["g"].shift(horizon)
    df["known"] = df["g"].shift(lag)  # the reading as of each date, given publication delays
    sample = df.iloc[::-1].iloc[::horizon].iloc[::-1]
    co = sample[["dg", "past"]].dropna()
    pr = sample[["known", "fwd"]].dropna()
    out = {"horizon": horizon, "lag": lag, "start": df.index[0].strftime("%Y-%m-%d"),
           "coincident": None, "n_coincident": len(co), "predictive": None, "n_predictive": len(pr),
           "significant": False}
    if len(co) >= min_obs:
        out["coincident"] = float(co["dg"].corr(co["past"]))
    if len(pr) >= min_obs:
        rho = float(pr["known"].rank().corr(pr["fwd"].rank()))  # Spearman, without needing scipy
        out["predictive"] = rho
        out["significant"] = bool(abs(rho) * np.sqrt(len(pr) - 1) > 1.96)
    have = df.dropna(subset=["fwd", "known"])
    band = sum((have["known"] > c).astype(int) for c in cuts)
    out["overall"] = {"mean": float(have["fwd"].mean()), "hit": float((have["fwd"] > 0).mean()),
                      "periods": len(have) / horizon}
    out["bands"] = [{"band": k, "mean": float(sub["fwd"].mean()) if len(sub) else None,
                     "hit": float((sub["fwd"] > 0).mean()) if len(sub) else None,
                     "periods": len(sub) / horizon}
                    for k, sub in ((k, have[band == k]) for k in range(len(cuts) + 1))]
    return out


# ----------------------------------------------------------------- breadth
def breadth(closes: pd.DataFrame) -> pd.DataFrame:
    """Daily breadth stats across a set of stocks (columns = tickers)."""
    closes = closes.sort_index()
    chg = closes.diff()
    adv = (chg > 0).sum(axis=1)
    dec = (chg < 0).sum(axis=1)
    unch = (chg == 0).sum(axis=1)
    total = (adv + dec + unch).replace(0, np.nan)
    out = pd.DataFrame({"advancing": adv, "declining": dec, "unchanged": unch})
    out["pct_adv"] = adv / total * 100
    out["pct_dec"] = dec / total * 100
    out["pct_unch"] = unch / total * 100
    for n in (20, 50, 200):
        sma = closes.rolling(n, min_periods=n).mean()
        valid = sma.notna() & closes.notna()
        out[f"above_{n}"] = ((closes > sma) & valid).sum(axis=1) / valid.sum(axis=1).replace(0, np.nan) * 100
    hi = closes.rolling(252, min_periods=200).max()
    lo = closes.rolling(252, min_periods=200).min()
    valid = hi.notna() & closes.notna()
    out["new_highs"] = ((closes >= hi) & valid).sum(axis=1)
    out["new_lows"] = ((closes <= lo) & valid).sum(axis=1)
    out["net_highs_pct"] = (out["new_highs"] - out["new_lows"]) / valid.sum(axis=1).replace(0, np.nan) * 100
    out["ad_line"] = (adv - dec).cumsum()
    return out.iloc[1:]


# ----------------------------------------------------------------- rotation
QUADRANTS = ["Leading", "Weakening", "Lagging", "Improving"]  # clockwise from top right


def weekly(closes: pd.DataFrame) -> pd.DataFrame:
    """Week-ending-Friday closes. The current week is labelled with its latest close date,
    not a Friday that hasn't happened yet."""
    wk = closes.resample("W-FRI").last()
    last = closes.index[-1]
    return wk.set_axis(wk.index.where(wk.index <= last, last))


def log_ratio(prices: pd.DataFrame, bench: pd.Series) -> pd.DataFrame:
    return np.log(prices.div(bench, axis=0))


def rs_trend(lr: pd.DataFrame, weeks: int, z_weeks: int = 52) -> pd.DataFrame:
    """Log relative strength vs its `weeks` average, in standard deviations of that gap
    over the last `z_weeks`: 0 = usual, +2 = unusually strong."""
    gap = lr - lr.rolling(weeks, min_periods=weeks).mean()
    return gap / gap.rolling(z_weeks, min_periods=z_weeks // 2).std()


def rotation_axes(lr: pd.DataFrame, trend: int, momentum: int, z_weeks: int = 52):
    """(trend, momentum): momentum is the change in trend over `momentum` weeks, so any
    swing in relative strength traces a clockwise loop."""
    x = rs_trend(lr, trend, z_weeks)
    return x, x.diff(momentum)


def quadrant(x: pd.DataFrame, y: pd.DataFrame) -> pd.DataFrame:
    """Index into QUADRANTS (float, NaN where either axis is missing)."""
    q = np.select([(x >= 0) & (y >= 0), (x >= 0) & (y < 0), (x < 0) & (y < 0)], [0, 1, 2], 3).astype(float)
    return pd.DataFrame(q, index=x.index, columns=x.columns).where(x.notna() & y.notna())


def clock_angle(x, y):
    """Position on the rotation clock in degrees: 0 = straight up, Leading 0-90,
    Weakening 90-180, Lagging 180-270, Improving 270-360."""
    return (90 - np.degrees(np.arctan2(y, x))) % 360


def rs_signal(lr: pd.DataFrame, spec: dict, z_weeks: int = 52) -> pd.DataFrame:
    """One candidate relative-strength measure (see config.ROTATION_CANDIDATES)."""
    kind, n = spec["kind"], spec["weeks"]
    if kind == "trend":
        return rs_trend(lr, n, z_weeks)
    if kind == "trend_change":
        return rs_trend(lr, n, z_weeks).diff(spec["change"])
    if kind == "return":
        return lr.shift(spec.get("skip", 0)) - lr.shift(n)
    if kind == "rsi":
        ratio = np.exp(lr)
        return pd.DataFrame({c: rsi(ratio[c].dropna(), n) for c in ratio}).reindex(lr.index)
    raise ValueError(f"unknown signal kind {kind!r}")


def cross_ic(signal: pd.DataFrame, fwd: pd.DataFrame, step: int = 1, min_names: int = 5) -> pd.Series:
    """Rank correlation across ETFs between a signal and the forward return, one value
    every `step` rows (non-overlapping when step = the forward horizon)."""
    ok = signal.notna() & fwd.notna()
    a, b = signal.where(ok).rank(axis=1), fwd.where(ok).rank(axis=1)
    a, b = a.sub(a.mean(axis=1), axis=0), b.sub(b.mean(axis=1), axis=0)
    ic = (a * b).sum(axis=1) / np.sqrt((a ** 2).sum(axis=1) * (b ** 2).sum(axis=1))
    keep = ok.sum(axis=1) >= min_names
    return ic.iloc[::step][keep.iloc[::step]].dropna()


def ic_summary(ic: pd.Series, min_n: int = 8) -> dict:
    if len(ic) < min_n:
        return {"ic": None, "t": None, "n": int(len(ic))}
    sd = ic.std()
    return {"ic": float(ic.mean()), "t": float(ic.mean() / sd * np.sqrt(len(ic))) if sd > 0 else None,
            "n": int(len(ic))}


def _events(signal: pd.DataFrame, fwd: pd.DataFrame, hit: pd.DataFrame, gap: int) -> np.ndarray:
    """Forward returns after each `hit`, per ETF, keeping events at least `gap` rows apart."""
    out = []
    for c in signal.columns:
        f = fwd[c].to_numpy()
        last = -gap
        for i in np.flatnonzero(hit[c].to_numpy() & ~np.isnan(f)):
            if i - last >= gap:
                out.append(f[i])
                last = i
    return np.array(out)


def rotation_stats(x: pd.DataFrame, y: pd.DataFrame, rel_rsi: pd.DataFrame, fwd: pd.DataFrame,
                   step: int, rsi_cuts: tuple[float, float]) -> dict:
    """How the map's readings were followed, on non-overlapping `step`-row periods.

    fwd is each ETF's forward log return vs the benchmark; it is measured here against the
    group's average, i.e. "did it beat the other members?"."""
    fwd = fwd.sub(fwd.mean(axis=1), axis=0)
    q = quadrant(x, y)
    qs, fs = q.iloc[::step].to_numpy(), fwd.iloc[::step].to_numpy()
    quads = {}
    for i, name in enumerate(QUADRANTS):
        v = fs[(qs == i) & ~np.isnan(fs)]
        quads[name] = {"mean": float(v.mean()) if len(v) else None, "n": int(len(v))}
    d = q.shift(-step).iloc[::step].to_numpy() - qs
    d = d[~np.isnan(d)] % 4
    moves = ({k: float(np.mean(d == v)) for k, v in (("stay", 0), ("clockwise", 1), ("opposite", 2),
                                                      ("counter", 3))} if len(d) else {})
    lo, hi = rsi_cuts
    over = _events(rel_rsi, fwd, rel_rsi >= hi, step)
    under = _events(rel_rsi, fwd, rel_rsi <= lo, step)
    extremes = {
        "overbought": {"mean": float(over.mean()) if len(over) else None, "n": int(len(over)),
                       "reversed": float((over < 0).mean()) if len(over) else None},
        "oversold": {"mean": float(under.mean()) if len(under) else None, "n": int(len(under)),
                     "reversed": float((under > 0).mean()) if len(under) else None},
    }
    return {"quadrants": quads, "moves": moves, **extremes}


# ----------------------------------------------------------------- returns
def period_returns(closes: pd.DataFrame, timeframes: list[str]) -> pd.DataFrame:
    """% return for each column over each timeframe, measured to its latest close."""
    lookback = {"1D": 1, "5D": 5, "20D": 20, "1Y": 252, "2Y": 504}
    rows = {}
    for col in closes.columns:
        s = closes[col].dropna()
        if len(s) < 2:
            continue
        last, d = s.iloc[-1], s.index[-1]
        r = {}
        for tf in timeframes:
            if tf in lookback:
                n = lookback[tf]
                base = s.iloc[-1 - n] if len(s) > n else np.nan
            else:
                start = d.to_period("Q").start_time if tf == "QTD" else pd.Timestamp(d.year, 1, 1)
                prior = s[s.index < start]
                base = prior.iloc[-1] if len(prior) else np.nan
            r[tf] = (last / base - 1) * 100 if base and np.isfinite(base) else np.nan
        r["last"] = float(last)
        r["date"] = d
        rows[col] = r
    return pd.DataFrame.from_dict(rows, orient="index")
