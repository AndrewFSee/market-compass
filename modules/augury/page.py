"""Risk forecasts page. Reads only what augury publishes into the hub data folder."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import apps, store, ui
from modules.augury import config as cfg

MODULE = cfg.MODULE


@st.cache_data(show_spinner=False)
def _cached(name: str, kind: str, stamp):
    return store.load_json(MODULE, name) if kind == "json" else store.load_frame(MODULE, name)


def load(name: str, kind: str = "frame"):
    return _cached(name, kind, store.stamp(MODULE, name))


def move(x: float) -> str:
    return "—" if pd.isna(x) else f"{x:+.1%}".replace("-", "−")


ZONE_COLOR = {"Green": "teal", "Yellow": "amber", "Red": "red"}

# ================================================================= header
st.title("Risk forecasts")
summary = load("summary", "json")
fc = load("forecast")
if not summary or fc is None or fc.empty:
    st.info("No risk forecasts yet. Run `python run_jobs.py --only augury` from the hub folder "
            "(it runs augury's `scripts/publish_to_hub.py` in that project's venv; the first run builds "
            "the track record and takes several minutes).")
    st.stop()

as_of = pd.Timestamp(summary["as_of"])
scores = summary.get("scores", {})
views = summary.get("iv_views", {})
st.caption(f"Forecasts from the close of {as_of:%b %d, %Y} · {fc['ticker'].nunique()} tickers · "
           f"from augury {summary.get('augury_version', '')} · "
           f"[open the full augury dashboard]({apps.launch_url(cfg.FULL_APP_URL)}) (starts it if needed)")
missed = int(np.busday_count(as_of.date() + pd.Timedelta(days=1), pd.Timestamp.now().date()))
if summary.get("demo"):
    st.warning("Demo data: synthetic prices, not market data.")
elif missed > cfg.STALE_BUSINESS_DAYS:
    st.warning(f"These forecasts are {missed} weekdays old. Check the hub refresh log for the augury job.")
if summary.get("errors"):
    with st.expander(f"{len(summary['errors'])} ticker(s) failed in the last run"):
        for t, e in summary["errors"].items():
            st.markdown(f"- **{t}**: `{e}`")

# ================================================================= ticker table
st.subheader("Next day, week and month")
groups = summary.get("groups") or {"All": sorted(fc["ticker"].unique())}
with st.container(border=True):
    group = ui.choice("Group", ["All", *groups], key="aug_group")
    tickers = [t for g, ts in groups.items() if group in ("All", g) for t in ts if t in set(fc["ticker"])]
    wide = fc.pivot(index="ticker", columns="horizon")
    rows = []
    for t in tickers:
        w = wide.loc[t]
        var1 = scores.get(t, {}).get("var", {}).get("0.01", {})
        rows.append({
            "Ticker": t,
            "Price": w[("last_price", 1)],
            "1d VaR 99%": -w[("var_99", 1)] * 100,
            "1d 90% range": f"{move(w[('lo_90', 1)] / w[('last_price', 1)] - 1)} / "
                            f"{move(w[('hi_90', 1)] / w[('last_price', 1)] - 1)}",
            "5d VaR 95%": -w[("var_95", 5)] * 100,
            "21d vol": w[("vol_ann", 21)] * 100,
            "21d realised": w[("realised_vol_21d", 21)] * 100,
            "21d 90% range": f"{move(w[('lo_90', 21)] / w[('last_price', 21)] - 1)} / "
                             f"{move(w[('hi_90', 21)] / w[('last_price', 21)] - 1)}",
            "VaR breaches (250d)": (f"{var1['recent_breaches']} / {var1['recent_expected']:.1f}"
                                    if var1 else "—"),
            "Zone": var1.get("recent_zone", "—"),
            "View": views[t].lstrip("^") if t in views else "—",
        })
    num = lambda label, fmt="%.1f", **kw: st.column_config.NumberColumn(label, format=fmt, **kw)  # noqa: E731
    ui.table(pd.DataFrame(rows), hide_index=True, height=min(38 * (len(rows) + 1), 560), column_config={
        "Price": num("Price", "%.2f"),
        "1d VaR 99%": num("1d VaR 99%", "%.1f%%", help="Loss the next session should exceed only 1% of the time"),
        "5d VaR 95%": num("5d VaR 95%", "%.1f%%", help="Loss over the next 5 sessions exceeded 5% of the time"),
        "21d vol": num("21d vol", help="Forecast volatility over the next 21 sessions, annualised, vol points"),
        "21d realised": num("21d realised", help="Volatility of the last 21 sessions, annualised"),
        "1d 90% range": st.column_config.TextColumn("1d 90% range", help="5th and 95th percentile of tomorrow's move"),
        "21d 90% range": st.column_config.TextColumn("21d 90% range"),
        "VaR breaches (250d)": st.column_config.TextColumn(
            "Breaches / expected", help="Last 250 sessions: days the loss exceeded the 1-day 99% VaR forecast "
                                        "made the night before, against the 2.5 a calibrated model would average"),
        "Zone": st.column_config.TextColumn("Basel zone", help="Green: 0-4 breaches in 250 days; yellow 5-9; red 10+"),
        "View": st.column_config.TextColumn("IV view", help="Implied-vol index blended 50/50 into the 21-day "
                                                            "variance (— = GJR alone)"),
    })
    st.caption("Moves are simple returns from the last close. No drift view: the median is close to today's price, "
               "so read the ranges as how far it could go, not where it is going.")

# ================================================================= ticker detail
st.subheader("Ticker detail")
tkr = st.selectbox("Ticker", tickers or sorted(fc["ticker"].unique()), key="aug_ticker")
risk = fc[fc["ticker"] == tkr].set_index("horizon")
bands, prices = load("bands"), load("prices")
left, right = st.columns([1.6, 1])
with left, st.container(border=True):
    st.markdown(f"**{tkr}: last 6 months and the next 21 sessions**")
    fig = go.Figure()
    if prices is not None:
        p = prices[prices["ticker"] == tkr].set_index("date")["close"].iloc[-126:]
        fig.add_trace(go.Scatter(x=p.index, y=p, mode="lines", line={"width": 1.6, "color": ui.PALETTE["grey"]},
                                 name="close", hovertemplate="%{x|%b %d}: %{y:,.2f}<extra></extra>"))
    if bands is not None:
        b = bands[bands["ticker"] == tkr].set_index("date")
        last = risk["last_price"].iloc[0]
        x = [as_of, *b.index]
        for lo, hi, alpha, name in (("q5", "q95", 0.22, "90% range"), ("q25", "q75", 0.42, "50% range")):
            fig.add_trace(go.Scatter(x=x, y=[last, *b[hi]], mode="lines", line={"width": 0}, hoverinfo="skip",
                                     showlegend=False))
            fig.add_trace(go.Scatter(x=x, y=[last, *b[lo]], mode="lines", line={"width": 0}, fill="tonexty",
                                     fillcolor=f"rgba(43,181,166,{alpha})", name=name, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=x, y=[last, *b["q50"]], mode="lines", name="median",
                                 line={"width": 2, "color": ui.PALETTE["teal"]},
                                 hovertemplate="%{x|%b %d}: %{y:,.2f}<extra>median</extra>"))
    fig.update_layout(height=300, margin={"l": 0, "r": 0, "t": 10, "b": 0}, hovermode="x unified",
                      legend={"orientation": "h", "y": 1.1, "x": 0})
    ui.chart(fig, key="aug_fan")

with right, st.container(border=True):
    st.markdown(f"**{tkr} forecast** · {summary.get('models', {}).get(tkr, '')}")
    t = pd.DataFrame({
        "Horizon": [f"{h} day{'s' * (h > 1)}" for h in risk.index],
        "VaR 99%": -risk["var_99"].to_numpy() * 100, "VaR 95%": -risk["var_95"].to_numpy() * 100,
        "ES 99%": -risk["es_99"].to_numpy() * 100,
        "P(up)": risk["p_up"].to_numpy() * 100,
    })
    pct = lambda label, **kw: st.column_config.NumberColumn(label, format="%.1f%%", **kw)  # noqa: E731
    ui.table(t, hide_index=True, column_config={
        "VaR 99%": pct("VaR 99%"), "VaR 95%": pct("VaR 95%"),
        "ES 99%": pct("ES 99%", help="Average loss on the worst 1% of outcomes"), "P(up)": pct("P(up)")})
    r21 = risk.loc[21]
    note = (f"21-day vol forecast {r21['vol_ann']:.1%} (GJR alone {r21['gjr_vol_ann']:.1%}, "
            f"last 21 days {r21['realised_vol_21d']:.1%})")
    if tkr in views and pd.notna(r21.get("iv")):
        note += f"; {views[tkr].lstrip('^')} at {r21['iv'] * 100:.1f} pulls it halfway to the implied level"
    st.caption(note + ".")

# ================================================================= track record
track = load("track")
sc = scores.get(tkr, {})
st.subheader(f"{tkr} track record")
if track is None or not sc.get("n"):
    st.info("No scored forecasts for this ticker yet.")
else:
    tr = track[(track["ticker"] == tkr) & (track["model"] == "augury") & (track["horizon"] == 1)]
    tr = tr.sort_values("origin")
    outcome = pd.DatetimeIndex(tr["origin"]).to_series().shift(-1)
    outcome.iloc[-1] = tr["origin"].iloc[-1] + pd.offsets.BDay(1)
    tr = tr.assign(date=outcome.to_numpy(), ret=np.expm1(tr["y"]), v1=np.expm1(tr["var_1"]),
                   v5=np.expm1(tr["var_5"]))

    v = sc["var"]["0.01"]
    cols = st.columns(4)
    with cols[0], st.container(border=True):
        st.metric("1% VaR breaches, last 250d", f"{v['recent_breaches']}",
                  f"{v['recent_breaches'] - v['recent_expected']:+.1f} vs expected", delta_color="inverse")
        ui.badge(f"{v['recent_zone'].upper()} ZONE", ZONE_COLOR.get(v["recent_zone"], "grey"))
    with cols[1], st.container(border=True):
        st.metric(f"1% VaR breach rate since {pd.Timestamp(sc['since']):%Y}", f"{v['rate']:.2%}",
                  f"{round((v['rate'] - 0.01) * 100, 2) + 0.0:+.2f} pts vs 1%", delta_color="off", delta_arrow="off")
        st.caption(f"Kupiec p {v['kupiec_p']:.2f} · clustering p {v['christoffersen_p']:.2f}")
    with cols[2], st.container(border=True):
        c90 = sc.get("coverage_90", {})
        st.metric("90% range hit rate, 1 day", f"{c90.get('1', np.nan):.1%}",
                  f"{round((c90.get('1', np.nan) - 0.9) * 100, 1) + 0.0:+.1f} pts vs 90%", delta_color="off", delta_arrow="off")
        st.caption(f"5 days {c90.get('5', np.nan):.1%} · 21 days {c90.get('21', np.nan):.1%}")
    with cols[3], st.container(border=True):
        skill = sc.get("skill")
        if skill:
            st.metric("Skill vs plain GJR, 1 day", f"{skill.get('1', np.nan):+.2%}",
                      f"21 days {skill.get('21', np.nan):+.2%}", delta_color="off", delta_arrow="off")
            st.caption("CRPS improvement from the implied-vol view (> 0 = better)")
        else:
            st.metric("Forecasts scored", f"{sc['n']:,}", 0, delta_description="plain GJR, no view")
            st.caption(f"Daily since {pd.Timestamp(sc['since']):%b %Y}")

    with st.container(border=True):
        win = ui.choice("Window", list(cfg.TRACK_WINDOWS), key="aug_window")
        n = cfg.TRACK_WINDOWS[win]
        d = tr if n is None else tr.iloc[-n:]
        hit = d["hit_1"].astype(bool)
        fig = go.Figure([
            go.Scatter(x=d["date"], y=d["ret"], mode="markers", name="daily return",
                       marker={"size": np.where(hit, 8, 4), "color": np.where(hit, ui.PALETTE["red"], ui.PALETTE["grey"])},
                       hovertemplate="%{x|%b %d, %Y}: %{y:+.2%}<extra></extra>"),
            go.Scatter(x=d["date"], y=d["v5"], mode="lines", name="95% VaR",
                       line={"width": 1, "color": ui.PALETTE["amber"]},
                       hovertemplate="%{y:+.2%}<extra>95% VaR</extra>"),
            go.Scatter(x=d["date"], y=d["v1"], mode="lines", name="99% VaR",
                       line={"width": 1.4, "color": ui.PALETTE["red"]},
                       hovertemplate="%{y:+.2%}<extra>99% VaR</extra>"),
        ])
        fig.update_layout(height=300, margin={"l": 0, "r": 0, "t": 10, "b": 0}, yaxis={"tickformat": ".0%"},
                          legend={"orientation": "h", "y": 1.1, "x": 0}, hovermode="closest")
        ui.chart(fig, key="aug_track")
        st.caption(f"Each day's return against the VaR forecast made at the previous close. Red dots broke the 99% "
                   f"VaR: {int(hit.sum())} in this window, where a calibrated model would average "
                   f"{len(d) * 0.01:.1f}.")

# ================================================================= all tickers' record
with st.expander("Track record, every ticker"):
    rows = []
    for t in tickers:
        s = scores.get(t, {})
        if not s.get("n"):
            continue
        v1, v5 = s["var"]["0.01"], s["var"]["0.05"]
        rows.append({"Ticker": t, "Since": pd.Timestamp(s["since"]).strftime("%Y-%m"), "Days": s["n"],
                     "1% VaR rate": v1["rate"], "Kupiec p": v1["kupiec_p"], "Clustering p": v1["christoffersen_p"],
                     "5% VaR rate": v5["rate"], "90% hit, 1d": s["coverage_90"].get("1"),
                     "90% hit, 21d": s["coverage_90"].get("21"),
                     "Skill vs GJR, 1d": (s.get("skill") or {}).get("1")})
    if rows:
        pct = lambda label, fmt="percent": st.column_config.NumberColumn(label, format=fmt)  # noqa: E731
        ui.table(pd.DataFrame(rows), hide_index=True, column_config={
            "1% VaR rate": pct("1% VaR rate"),
            "Kupiec p": pct("Kupiec p", "%.2f"), "Clustering p": pct("Clustering p", "%.2f"),
            "5% VaR rate": pct("5% VaR rate"), "90% hit, 1d": pct("90% hit, 1d"),
            "90% hit, 21d": pct("90% hit, 21d"), "Skill vs GJR, 1d": pct("Skill vs GJR, 1d")})
        st.caption("Out of sample: each forecast used only the two years of returns before it (refit every 21 "
                   "days). A p-value below 0.05 means the breach count (Kupiec) or their bunching (clustering) is "
                   "unlikely for a calibrated model.")

with st.expander("Model and caveats"):
    st.markdown(
        "- **Model:** GJR-GARCH(1,1) with skewed-t shocks, fitted on the last 504 sessions, zero drift. This was "
        "augury's best model out of sample (2012-2026 walk-forward on SPY, QQQ, IWM, TLT, GLD: best CRPS at 1, 5 "
        "and 21 days, and the only one to pass the 1% VaR backtests on most assets).\n"
        "- **Implied-vol view** (SPY, QQQ, IWM, TLT, GLD): the 21-day variance is blended 50/50 with the "
        "implied-vol index (VIX, VXN, VIX, MOVE, GVZ), keeping GJR's shape. It improved CRPS by 0.3-0.6% on four "
        "of the five with all VaR backtests green. TLT's MOVE index is in basis points of Treasury yields, so it is "
        "rescaled to TLT's realised variance first. Other tickers use GJR alone.\n"
        "- **Single stocks:** earnings jumps are not modelled, so expect more breaches around report dates.\n"
        "- **How this differs from the Volatility page:** that page forecasts the level of 21-day realised vol "
        "(HAR + implied, earnings-adjusted). This one forecasts the whole distribution of returns, so it gives "
        "VaR and price ranges at 1, 5 and 21 days, and is scored on those."
    )
