"""Growth vs value timing calculations. Pure pandas, no I/O.

French's 2x3 size / book-to-market portfolios are formed each June; book is for fiscal year t-1 and
counts as known from July t (their convention). Per month m in Jul t .. Jun t+1:

* book / price now = French's VW book(t-1) / ME(June t), divided by the portfolio's gross return since
  June (price updated monthly; dividends included, which the growth and value sides share)
* value spread = log(value B/P) - log(growth B/P)
* investment gap = growth minus value VW asset growth, profitability gap = growth minus value VW OP

z-scores use only earlier months (expanding mean / sd). The rule holds value when the investment-gap
z is above the threshold and growth otherwise; a month-end reading is held through the next month
(or ``lag`` months later), with a cost per switch.
"""
from __future__ import annotations

import io

import numpy as np
import pandas as pd


# ------------------------------------------------------------------ French's file
def parse_sections(text: str) -> dict[str, pd.DataFrame]:
    """Every table in a French CSV, keyed by its title (whitespace collapsed). Index: the raw
    yyyymm / yyyy integer; values numeric with French's -99.99 / -999 as NaN."""
    lines = text.replace("\r\n", "\n").split("\n")   # titles carry stray \r inside: split on \n only
    out, i = {}, 0
    while i < len(lines):
        if lines[i].startswith(",") and i > 0:
            title = " ".join(lines[i - 1].split())
            body, j = [lines[i]], i + 1
            while j < len(lines) and lines[j].split(",")[0].strip().isdigit():
                body.append(lines[j])
                j += 1
            d = pd.read_csv(io.StringIO("\n".join(body)), index_col=0)
            d.columns = [c.strip() for c in d.columns]
            out[title] = d.apply(pd.to_numeric, errors="coerce").replace([-99.99, -999.0], np.nan)
            i = j
        else:
            i += 1
    return out


def data_through(text: str) -> str | None:
    """'This file was created by using the 202609 CRSP database.' -> '2026-09'."""
    for line in text.splitlines()[:5]:
        for tok in line.split():
            if len(tok) == 6 and tok.isdigit():
                return f"{tok[:4]}-{tok[4:]}"
    return None


def section(sections: dict[str, pd.DataFrame], key: str) -> pd.DataFrame:
    hits = [t for t in sections if key in t]
    if not hits:
        raise KeyError(f"no section with '{key}' in French's file (got: {list(sections)[:12]})")
    d = sections[hits[0]]
    d = d[d.index.astype(str).str.len() == 6]                   # monthly rows only
    d.index = pd.to_datetime(d.index.astype(str), format="%Y%m") + pd.offsets.MonthEnd(0)
    return d


def expanding_z(x: pd.Series, min_obs: int) -> pd.Series:
    """(x - mean of earlier values) / sd of earlier values; NaN until ``min_obs`` earlier values exist."""
    past = x.shift(1)
    return (x - past.expanding(min_obs).mean()) / past.expanding(min_obs).std()


def formation_year(idx: pd.DatetimeIndex) -> np.ndarray:
    """June-t formation year of each month (Jul t .. Jun t+1 -> t)."""
    return np.where(idx.month >= 7, idx.year, idx.year - 1)


def panel(sections: dict[str, pd.DataFrame], growth: str, value: str, keys: dict, z_min: int) -> pd.DataFrame:
    ret = section(sections, keys["ret"]) / 100
    bm = section(sections, keys["bm"])
    op, inv = section(sections, keys["op"]), section(sections, keys["inv"])
    out = pd.DataFrame({"ret_g": ret[growth], "ret_v": ret[value]})

    def bm_now(col: str) -> pd.Series:
        r = ret[col]
        since_june = (1 + r).groupby(formation_year(r.index)).cumprod()
        return bm[col].reindex(r.index) / since_june

    out["bm_g"], out["bm_v"] = bm_now(growth), bm_now(value)
    out["value_spread"] = np.log(out["bm_v"] / out["bm_g"])
    out["inv_g"], out["inv_v"] = inv[growth].reindex(out.index), inv[value].reindex(out.index)
    out["op_g"], out["op_v"] = op[growth].reindex(out.index), op[value].reindex(out.index)
    out["inv_gap"] = out["inv_g"] - out["inv_v"]
    out["op_gap"] = out["op_g"] - out["op_v"]
    for src, z in (("inv_gap", "z_inv"), ("op_gap", "z_op"), ("value_spread", "z_vs")):
        s = out[src].dropna()
        out[z] = expanding_z(s, z_min).reindex(out.index)
    return out


# ------------------------------------------------------------------ rule and backtest
def rule_state(z: pd.Series, threshold: float = 0.0) -> pd.Series:
    """'V' when z > threshold, 'G' otherwise, NaN while z is NaN."""
    return pd.Series(np.where(z > threshold, "V", "G"), index=z.index).where(z.notna())


def once_a_year(state: pd.Series, month: int = 7) -> pd.Series:
    """Keep each year's reading from ``month`` (the new portfolios) until the next one."""
    return state.where(state.index.month == month).ffill().where(state.notna())


def backtest(state: pd.Series, ret_g: pd.Series, ret_v: pd.Series, cost: float, lag: int = 0) -> pd.DataFrame:
    """Monthly returns of holding the side ``state`` names, decided at month-end and held from the
    month after, ``lag`` months late. Columns rot, blend (50/50), g (1 in growth), sw (switch)."""
    pos = state.shift(1 + lag).dropna()
    pos = pos[pos.index.isin(ret_g.index)]
    g, v = ret_g.reindex(pos.index), ret_v.reindex(pos.index)
    sw = (pos != pos.shift(1)) & pos.shift(1).notna()
    rot = pd.Series(np.where(pos == "G", g, v), index=pos.index) - cost * sw
    return pd.DataFrame({"rot": rot, "blend": (g + v) / 2, "ret_g": g, "ret_v": v,
                         "g": (pos == "G").astype(float), "sw": sw.astype(int)}).dropna(subset=["ret_g", "ret_v"])


def nw_t(x, lags: int = 3) -> float:
    """t-statistic of the mean with Newey-West standard errors."""
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 12:
        return float("nan")
    e = x - x.mean()
    v = e @ e / n + 2 * sum((1 - k / (lags + 1)) * (e[k:] @ e[:-k]) / n for k in range(1, lags + 1))
    return float(x.mean() / np.sqrt(v / n)) if v > 0 else float("nan")


def summarize(bt: pd.DataFrame, start: str | None = None, end: str | None = None) -> dict:
    """Excess over 50/50 and 'timing' over a fixed mix with the same average growth share, %/yr."""
    b = bt.loc[start:end]
    if len(b) < 12:
        return {"months": len(b)}
    w = b["g"].mean()
    ex = b["rot"] - b["blend"]
    timing = b["rot"] - (w * b["ret_g"] + (1 - w) * b["ret_v"])
    return {"start": str(b.index[0].date()), "end": str(b.index[-1].date()), "months": int(len(b)),
            "excess": float(ex.mean() * 1200), "t": nw_t(ex), "timing": float(timing.mean() * 1200),
            "t_timing": nw_t(timing), "share_growth": float(w),
            "switches_per_year": float(b["sw"].sum() / (len(b) / 12))}


# ------------------------------------------------------------------ one reading per year
def annual(p: pd.DataFrame) -> pd.DataFrame:
    """Each July (new portfolios, new accounting year): the readings and value minus growth (log)
    over the next 12 months (NaN until all 12 are in)."""
    lv = np.log1p(p["ret_v"]) - np.log1p(p["ret_g"])
    rows = []
    for jul in p.index[p.index.month == 7]:
        nxt = lv.loc[jul + pd.offsets.MonthEnd(1):jul + pd.offsets.MonthEnd(12)]
        rows.append({"year": jul.year, **{c: p.at[jul, c] for c in ("inv_gap", "z_inv", "op_gap", "z_op",
                                                                     "value_spread", "z_vs", "inv_g", "inv_v")},
                     "next_12m": float(nxt.sum()) if len(nxt) == 12 else np.nan})
    return pd.DataFrame(rows).set_index("year")


def rank_corr(a: pd.Series, b: pd.Series) -> float:
    d = pd.concat([a, b], axis=1).dropna()
    return float(d.iloc[:, 0].rank().corr(d.iloc[:, 1].rank())) if len(d) > 3 else float("nan")


def annual_test(a: pd.DataFrame, col: str, start: int | None = None, end: int | None = None,
                drop: tuple[int, int] | None = None) -> dict:
    """OLS of next-12-month value minus growth on the July reading (standardised), one point a year."""
    d = a.loc[start:end, [col, "next_12m"]].dropna()
    if drop:
        d = d.drop(index=[y for y in range(drop[0], drop[1] + 1) if y in d.index])
    if len(d) < 8:
        return {"n": len(d)}
    x = (d[col] - d[col].mean()) / d[col].std()
    b, c = np.polyfit(x, d["next_12m"], 1)
    resid = d["next_12m"] - (b * x + c)
    se = resid.std(ddof=2) / np.sqrt((x ** 2).sum())
    return {"start": int(d.index[0]), "end": int(d.index[-1]), "n": int(len(d)), "slope": float(b * 100),
            "t": float(b / se), "rank_corr": rank_corr(d[col], d["next_12m"])}


def by_decade(a: pd.DataFrame, col: str) -> dict:
    out = {}
    for dec in range(int(a.index.min()) // 10 * 10, int(a.index.max()) + 1, 10):
        d = a.loc[dec:dec + 9, [col, "next_12m"]].dropna()
        if len(d) >= 5:
            out[f"{dec}s"] = rank_corr(d[col], d["next_12m"])
    return out


# ------------------------------------------------------------------ live (SEC filings) vs French
def to_month(df: pd.DataFrame, date_col: str = "date") -> pd.DataFrame:
    """Rows keyed by month-end (the last row of each month wins)."""
    d = df.copy()
    d["month"] = pd.to_datetime(d[date_col]) + pd.offsets.MonthEnd(0)
    return d.sort_values(date_col).drop_duplicates("month", keep="last").set_index("month")


def calibrate(french: pd.Series, live: pd.Series, lead: int = 0) -> dict:
    """OLS of French's investment gap ``lead`` months later on the SEC-based one, over the months both exist."""
    ahead = french.copy()
    if lead:
        ahead.index = ahead.index - pd.offsets.MonthEnd(lead)     # French at m + lead, labelled m
    d = pd.concat([ahead.rename("f"), live.rename("l")], axis=1).dropna()
    if len(d) < 12:
        return {"n": len(d), "lead": lead}
    b, c = np.polyfit(d["l"], d["f"], 1)
    return {"n": int(len(d)), "lead": lead, "start": str(d.index[0].date()), "end": str(d.index[-1].date()),
            "corr": float(d["f"].corr(d["l"])), "slope": float(b), "intercept": float(c)}


def live_reading(cal: dict, live_gap: float, french_gap: pd.Series, threshold: float, min_corr: float,
                 min_months: int) -> dict:
    """Put the latest SEC-based gap on French's scale and z-score it against all French readings."""
    hist = french_gap.dropna()
    if cal.get("n", 0) < min_months or "slope" not in cal or not np.isfinite(live_gap):
        return {"usable": False, "tracking": False, "reason": f"only {cal.get('n', 0)} overlapping months"}
    mapped = cal["intercept"] + cal["slope"] * live_gap
    z = (mapped - hist.mean()) / hist.std()
    tracking = cal["corr"] >= min_corr
    return {"usable": True, "tracking": bool(tracking), "mapped_gap": float(mapped), "z": float(z),
            "signal": ("value" if z > threshold else "growth"),
            "reason": None if tracking else f"correlation {cal['corr']:.2f} with French's reading {cal['lead']} months later"}
