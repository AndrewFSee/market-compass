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


# ----------------------------------------------------------------- sector internals
def _cap_weights_basis(closes: pd.DataFrame, caps: pd.Series) -> pd.DataFrame:
    """Market cap through time, holding today's share count fixed (caps / last price)."""
    last = closes.ffill().iloc[-1]
    shares = caps.reindex(closes.columns).fillna(caps.median()) / last
    return closes * shares


def sector_internals(closes: pd.DataFrame, sector_of: pd.Series, bench: pd.Series, caps: pd.Series,
                     window: int = 20) -> pd.DataFrame:
    """Daily participation inside each sector, long format (date, sector, ...):
    beating   - % of members whose `window`-day return beat the benchmark's
    above_50 / above_200 - % of members above their 50- / 200-day average
    net_highs - % of members that made a new 52-week high within `window` days, minus lows
    ew_cw     - equal-weighted minus cap-weighted `window`-day return, in % points
    rel_cw    - cap-weighted `window`-day return minus the benchmark's, in % points"""
    closes = closes.sort_index()
    bench = bench.reindex(closes.index).ffill()
    ret = closes / closes.shift(window) - 1
    bret = bench / bench.shift(window) - 1
    beat = ret.gt(bret, axis=0).astype(float).where(ret.notna()).where(bret.notna(), axis=0)
    flags = {}
    for n in (50, 200):
        sma = closes.rolling(n, min_periods=n).mean()
        flags[f"above_{n}"] = (closes > sma).astype(float).where(sma.notna() & closes.notna())
    hi = closes.rolling(252, min_periods=200).max()
    lo = closes.rolling(252, min_periods=200).min()
    valid = hi.notna() & closes.notna()
    made_high = (closes >= hi).where(valid).astype(float).rolling(window, min_periods=1).max()
    made_low = (closes <= lo).where(valid).astype(float).rolling(window, min_periods=1).max()
    net = (made_high - made_low).where(valid)
    w0 = _cap_weights_basis(closes, caps).shift(window).where(ret.notna())
    out = []
    for sector, members in sector_of.groupby(sector_of):
        cols = [c for c in members.index if c in closes.columns]
        if not cols:
            continue
        cw = (ret[cols] * w0[cols]).sum(axis=1, min_count=1) / w0[cols].sum(axis=1, min_count=1)
        out.append(pd.DataFrame({
            "sector": sector,
            "beating": beat[cols].mean(axis=1) * 100,
            "above_50": flags["above_50"][cols].mean(axis=1) * 100,
            "above_200": flags["above_200"][cols].mean(axis=1) * 100,
            "net_highs": net[cols].mean(axis=1) * 100,
            "ew_cw": (ret[cols].mean(axis=1) - cw) * 100,
            "rel_cw": (cw - bret) * 100,
            "members": ret[cols].notna().sum(axis=1),
        }))
    if not out:
        return pd.DataFrame(columns=["date", "sector", "beating", "above_50", "above_200", "net_highs",
                                     "ew_cw", "rel_cw", "members"])
    return pd.concat(out).rename_axis("date").reset_index()


def contributions(closes: pd.DataFrame, sector_of: pd.Series, bench: pd.Series, caps: pd.Series,
                  window: int) -> pd.DataFrame:
    """Each member's share of its sector's cap-weighted move vs the benchmark over the last
    `window` days, in % points: weight at the start x (return - benchmark return).
    Contributions within a sector add up to the sector's relative return."""
    closes = closes.sort_index().ffill()
    if len(closes) <= window:
        return pd.DataFrame(columns=["sector", "ticker", "weight", "ret", "rel", "contrib"])
    bench = bench.reindex(closes.index).ffill()
    start, end = closes.iloc[-1 - window], closes.iloc[-1]
    r = end / start - 1
    b = bench.iloc[-1] / bench.iloc[-1 - window] - 1
    cap0 = _cap_weights_basis(closes, caps).iloc[-1 - window]
    rows = []
    for sector, members in sector_of.groupby(sector_of):
        cols = [c for c in members.index if c in closes.columns and pd.notna(r.get(c)) and pd.notna(cap0.get(c))]
        if not cols:
            continue
        w = cap0[cols] / cap0[cols].sum()
        rows.append(pd.DataFrame({"sector": sector, "ticker": cols, "weight": w.to_numpy() * 100,
                                  "ret": r[cols].to_numpy() * 100, "rel": (r[cols] - b).to_numpy() * 100,
                                  "contrib": (w * (r[cols] - b)).to_numpy() * 100}))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(
        columns=["sector", "ticker", "weight", "ret", "rel", "contrib"])


def confirmation_stats(beating: pd.DataFrame, momentum: pd.DataFrame, fwd: pd.DataFrame, step: int,
                       broad: float) -> dict:
    """Did participation inside a sector tell you whether its rotation would last?

    beating: % of members beating the benchmark; momentum: the rotation map's momentum;
    fwd: forward log return vs the benchmark (measured here vs the sectors' average).
    All weekly, columns = sector ETFs, sampled every `step` rows (non-overlapping)."""
    cols = [c for c in beating.columns if c in momentum.columns and c in fwd.columns]
    idx = beating.index.intersection(momentum.index).intersection(fwd.index)
    b, m, f = beating.loc[idx, cols], momentum.loc[idx, cols], fwd.loc[idx, cols]
    f = f.sub(f.mean(axis=1), axis=0)
    bs, ms, fs = b.iloc[::step].to_numpy(), m.iloc[::step].to_numpy(), f.iloc[::step].to_numpy()
    ok = ~(np.isnan(bs) | np.isnan(ms) | np.isnan(fs))
    cases = {
        "rising_broad": (ms > 0) & (bs >= broad), "rising_narrow": (ms > 0) & (bs < broad),
        "falling_broad": (ms <= 0) & (bs < broad), "falling_narrow": (ms <= 0) & (bs >= broad),
    }
    out = {}
    for k, mask in cases.items():
        v = fs[mask & ok]
        out[k] = {"mean": float(v.mean()) if len(v) else None, "hit": float((v > 0).mean()) if len(v) else None,
                  "n": int(len(v))}
    out["ic_beating"] = ic_summary(cross_ic(b, f, step, min_names=5))
    have = b.dropna(how="all").index
    out["start"] = have[0].strftime("%Y-%m-%d") if len(have) else None
    out["end"] = have[-1].strftime("%Y-%m-%d") if len(have) else None
    return out


# ----------------------------------------------------------------- leadership
def relative_returns(weekly_prices: pd.DataFrame, bench: pd.Series, weeks: int) -> pd.DataFrame:
    """Trailing `weeks` return of each column minus the benchmark's, in % points (log-based)."""
    lr = log_ratio(weekly_prices, bench)
    return (np.exp(lr.diff(weeks)) - 1) * 100


def dispersion(daily: pd.DataFrame, weeks: int = 4, corr_days: int = 63) -> pd.DataFrame:
    """Weekly: spread of the columns' trailing `weeks` returns (cross-sectional std, % points)
    and their average pairwise correlation of daily returns over the last `corr_days`."""
    wk = weekly(daily)
    disp = ((wk / wk.shift(weeks) - 1) * 100).std(axis=1)
    rets = daily.pct_change(fill_method=None)
    corr = {}
    for d in wk.index:
        window = rets.loc[:d].iloc[-corr_days:].dropna(axis=1, thresh=int(corr_days * 0.8))
        if window.shape[1] < 3 or len(window) < corr_days:
            continue
        c = window.corr().to_numpy()
        corr[d] = float(c[~np.eye(len(c), dtype=bool)].mean())
    return pd.DataFrame({"dispersion": disp, "correlation": pd.Series(corr, dtype=float)}).dropna(how="all")


# ----------------------------------------------------------------- cross-asset
def driver_change(s: pd.Series, weeks: int, kind: str) -> pd.Series:
    """Change over `weeks` rows: % change for prices (yahoo), level change for rates/spreads (fred)."""
    return (s / s.shift(weeks) - 1) * 100 if kind == "yahoo" else s.diff(weeks)


def cross_asset_check(rel: pd.Series, driver: pd.Series, kind: str, sign: int, weeks: int,
                      corr_weeks: int) -> dict:
    """Does a sector's relative strength (weekly log ratio vs the benchmark) move with its driver?

    Recent: both changes over `weeks` and whether they agree with the expected sign.
    Link: correlation of weekly changes over the last `corr_weeks`, and over the whole history,
    signed so that positive = moving the expected way."""
    df = pd.DataFrame({"rel": rel, "drv": driver}).dropna()
    if len(df) <= weeks:
        return {}
    rel_chg = (np.exp(df["rel"].diff(weeks)) - 1) * 100
    drv_chg = driver_change(df["drv"], weeks, kind)
    weekly_chg = pd.DataFrame({"rel": df["rel"].diff(), "drv": driver_change(df["drv"], 1, kind)}).dropna()
    recent = weekly_chg.iloc[-corr_weeks:]
    r_now, d_now = float(rel_chg.iloc[-1]), float(drv_chg.iloc[-1])
    return {
        "rel_change": r_now, "driver_change": d_now,
        "agrees": bool(np.sign(r_now) == sign * np.sign(d_now)) if r_now and d_now else None,
        "corr_recent": float(recent["rel"].corr(recent["drv"]) * sign) if len(recent) > 10 else None,
        "corr_all": float(weekly_chg["rel"].corr(weekly_chg["drv"]) * sign) if len(weekly_chg) > 10 else None,
        "since": df.index[0].strftime("%Y-%m-%d"),
    }


# ----------------------------------------------------------------- fund flows
def fund_flows(hist: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Daily net flows in dollars (change in shares x NAV) and net assets, date x ticker.

    Not investor money, so left out:
    - a share split (share count up, NAV down by the same factor): set to 0;
    - a fund's first quarter, and any day moving more than half its assets: launches and
      structural events such as XLRE's 2016 spin-off from XLF (shares x23 in a day)."""
    nav = hist.pivot_table(index="date", columns="ticker", values="nav")
    shares = hist.pivot_table(index="date", columns="ticker", values="shares")
    tna = hist.pivot_table(index="date", columns="ticker", values="tna")
    s_ratio, n_ratio = shares / shares.shift(), nav.shift() / nav
    split = (s_ratio > 1.4) & ((s_ratio / n_ratio - 1).abs() < 0.05)
    flows = (shares.diff() * nav).mask(split, 0.0)
    flows = flows.mask((flows / tna.shift()).abs() > 0.5)
    young = shares.notna().cumsum() <= 63
    return flows.mask(young), tna


def flow_share(flows: pd.DataFrame, tna: pd.DataFrame, days: int) -> pd.DataFrame:
    """Net flows over the last `days` as % of net assets at the start of the window."""
    return flows.rolling(days, min_periods=max(1, days // 2)).sum() / tna.shift(days) * 100


def extreme_spread(signal: pd.DataFrame, fwd: pd.DataFrame, step: int, k: int = 2) -> dict:
    """Forward return (vs the group) of the k highest-signal columns minus the k lowest,
    on non-overlapping dates."""
    fwd = fwd.sub(fwd.mean(axis=1), axis=0)
    vals = []
    for d in signal.index[::step]:
        s, f = signal.loc[d], fwd.loc[d] if d in fwd.index else None
        if f is None:
            continue
        ok = s.notna() & f.notna()
        if ok.sum() < 2 * k + 1:
            continue
        order = s[ok].sort_values()
        vals.append(f[order.index[-k:]].mean() - f[order.index[:k]].mean())
    v = pd.Series(vals, dtype=float)
    if len(v) < 8:
        return {"mean": None, "t": None, "hit": None, "n": int(len(v))}
    return {"mean": float(v.mean()), "t": float(v.mean() / v.std() * np.sqrt(len(v))) if v.std() > 0 else None,
            "hit": float((v > 0).mean()), "n": int(len(v))}


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


# ----------------------------------------------------------------- global markets & headline economy
def market_snapshot(closes: pd.DataFrame, spark_weeks: int = 52) -> pd.DataFrame:
    """Per ticker: last close; % change over 1 day, 1 week, month-to-date, year-to-date and 1 year;
    the 52-week range and where the last close sits in it (0 = low, 100 = high); % distance from
    the 50- and 200-day averages and whether the 200-day is higher than 20 sessions ago; 14-day
    RSI; and the last ``spark_weeks`` weekly closes for a sparkline."""
    rows = {}
    for col in closes.columns:
        s = closes[col].dropna()
        if len(s) < 30:
            continue
        last, d = float(s.iloc[-1]), s.index[-1]

        def change(base) -> float:
            return (last / base - 1) * 100 if base and np.isfinite(base) else np.nan

        def back(n: int) -> float:
            return s.iloc[-1 - n] if len(s) > n else np.nan

        def before(start: pd.Timestamp) -> float:
            prior = s[s.index < start]
            return prior.iloc[-1] if len(prior) else np.nan

        year = s[s.index > d - pd.DateOffset(years=1)]
        lo, hi = float(year.min()), float(year.max())
        sma50, sma200 = s.rolling(50).mean(), s.rolling(200).mean()
        rising = (bool(sma200.iloc[-1] > sma200.iloc[-21])
                  if len(sma200.dropna()) > 20 else None)
        rows[col] = {
            "date": d, "last": last, "1D": change(back(1)), "1W": change(back(5)),
            "MTD": change(before(pd.Timestamp(d.year, d.month, 1))), "YTD": change(before(pd.Timestamp(d.year, 1, 1))),
            "1Y": change(back(252)) if len(s) > 252 else np.nan,
            "low_52w": lo, "high_52w": hi, "range_pos": (last - lo) / (hi - lo) * 100 if hi > lo else np.nan,
            "vs_50d": change(sma50.iloc[-1]), "vs_200d": change(sma200.iloc[-1]), "sma200_rising": rising,
            "rsi14": float(rsi(s).iloc[-1]),
            "spark": s.resample("W-FRI").last().dropna().tail(spark_weeks).round(4).tolist(),
        }
    return pd.DataFrame.from_dict(rows, orient="index")


def headline_series(fred: dict, spec: dict) -> pd.Series | None:
    """One headline number's history, transformed as ``spec['kind']`` says."""
    parts = [_clean_series(fred.get(sid)) for sid in spec["series"]]
    if any(p is None or p.empty for p in parts):
        return None
    s = parts[0]
    kind = spec["kind"]
    if kind in ("range", "spread"):
        both = pd.concat(parts, axis=1, join="inner").dropna()
        s = both.iloc[:, 1] if kind == "range" else both.iloc[:, 0] - both.iloc[:, 1]
    elif kind == "yoy":
        s = (s / s.shift(12) - 1) * 100
    elif kind == "mom_diff":
        s = s.diff()
    elif kind == "saar":
        s = ((s / s.shift(1)) ** 4 - 1) * 100
    return s.dropna()


def headline_econ(fred: dict, specs: list[dict], spark: int = 24) -> list[dict]:
    """Latest value of each headline number with the one before it. Daily series compare with a
    month earlier and their sparkline uses month-ends; monthly and quarterly series compare with
    the previous release. A range (the Fed's target) reports its lower bound too."""
    out = []
    for spec in specs:
        item = {k: spec.get(k) for k in ("key", "label", "unit", "kind", "release")}
        item["up_is_good"] = spec.get("up_is_good", True)
        s = headline_series(fred, spec)
        if s is None or s.empty:
            out.append({**item, "value": None})
            continue
        raw = _clean_series(fred.get(spec["series"][0]))   # spacing of the release, before transforms
        gap = pd.Series(raw.index).diff().dt.days.median()
        daily = gap < 7
        d = s.index[-1]
        if daily:
            prior_s = s[s.index <= d - pd.DateOffset(months=1)]
            prior = float(prior_s.iloc[-1]) if len(prior_s) else None
            line = s.resample("ME").last().dropna()
            line.iloc[-1] = s.iloc[-1]
        else:
            prior = float(s.iloc[-2]) if len(s) > 1 else None
            line = s
        freq = "daily" if daily else ("quarterly" if gap > 60 else "monthly")
        item.update({"value": float(s.iloc[-1]), "prior": prior,
                     "change": float(s.iloc[-1]) - prior if prior is not None else None,
                     "date": d.strftime("%Y-%m-%d"), "freq": freq,
                     "spark": [round(float(x), 4) for x in line.tail(spark)]})
        if spec["kind"] == "range":
            lo = _clean_series(fred.get(spec["series"][0]))
            item["low"] = float(lo.loc[:d].iloc[-1]) if lo is not None and len(lo.loc[:d]) else None
        out.append(item)
    return out
