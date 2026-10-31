"""Volatility page. Reads only what stochastic-vol-surface publishes into the hub data folder."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import apps, store, ui
from modules.vol import config as cfg

MODULE = cfg.MODULE


@st.cache_data(show_spinner=False)
def _cached(name: str, kind: str, stamp):
    return store.load_json(MODULE, name) if kind == "json" else store.load_frame(MODULE, name)


def load(name: str, kind: str = "frame"):
    return _cached(name, kind, store.stamp(MODULE, name))


# ================================================================= header
st.title("Volatility")
summary = load("summary", "json")
if not summary:
    st.info("No vol data yet. Run `python run_jobs.py --only vol` from the hub folder "
            "(it runs stochastic-vol-surface's `scripts/publish_to_hub.py` in that project's venv).")
    st.stop()

as_of = pd.Timestamp(summary["as_of"])
now = pd.Timestamp.now()
# sessions since the last surface; today counts once its after-close scrape should have run
missed = int(np.busday_count(as_of.date() + pd.Timedelta(days=1),
                             (now + pd.Timedelta(days=1 if now.hour >= cfg.SCRAPE_DONE_HOUR else 0)).date()))
st.caption(f"Surfaces through {as_of:%b %d, %Y} · {summary['tickers']} tickers since {summary['history_start']} · "
           f"from stochastic-vol-surface · [open the full vol dashboard]({apps.launch_url(cfg.FULL_APP_URL)}) (starts it if needed)")
if missed > cfg.STALE_BUSINESS_DAYS:
    st.warning(f"The option scrapers have not produced data for {missed} weekday{'s' * (missed != 1)}. "
               "Check the DailyScraper / "
               "PrecloseScraper tasks in Task Scheduler (Windows Smart App Control has been blocking them).")
health = summary.get("last_health")
if health and not health.get("ok"):
    with st.expander("The last scraper health check reported problems"):
        for c in health.get("checks", []):
            st.markdown(f"- {'✅' if c['ok'] else '⚠️'} **{c['name']}**: {c['message']}")
if summary.get("stale_tickers"):
    st.caption("No recent surface for: " + ", ".join(summary["stale_tickers"]))

# ================================================================= market vols
market = load("market")
if market is not None and not market.empty:
    cols = st.columns(len(cfg.MARKET_VOLS))
    for col, (key, label) in zip(cols, cfg.MARKET_VOLS.items()):
        s = market[key].dropna() if key in market else pd.Series(dtype=float)
        if len(s) > 5:
            col.metric(label, f"{s.iloc[-1]:.1f}", f"{s.iloc[-1] - s.iloc[-6]:+.1f} (5d)", delta_color="inverse")
    if {"mkt_vix", "mkt_vix3m"} <= set(market.columns):
        v, v3 = market["mkt_vix"].dropna().iloc[-1], market["mkt_vix3m"].dropna().iloc[-1]
        st.caption(f"VIX term structure: 3-month minus spot = {v3 - v:+.1f} pts "
                   f"({'upward sloping, the calm-market norm' if v3 > v else 'inverted, usually a stress signal'}).")

# ================================================================= ticker table
ov = load("overview")
st.subheader("Implied vol by ticker")
if ov is None or ov.empty:
    st.info("No surfaces published.")
    st.stop()

with st.container(border=True):
    group = ui.choice("Group", ["All", *cfg.GROUPS], key="vol_group")
    view = ov if group == "All" else ov[ov["ticker"].isin(cfg.GROUPS[group])]
    order = {t: i for i, t in enumerate(t for g in cfg.GROUPS.values() for t in g)}
    view = view.assign(_o=view["ticker"].map(order).fillna(999)).sort_values("_o")
    pts = 100  # decimals -> vol points
    table = pd.DataFrame({
        "Ticker": view["ticker"],
        "30d ATM": view["atm_30d"] * pts,
        "5d chg": view["atm_30d_d5"] * pts,
        "1y pctile": view["atm_30d_pct252"],
        "25d RR": view["rr25_30d"] * pts,
        "30→91d slope": view["ts_30_91"] * pts,
        "VRP": view["vrp_30d"] * pts,
        "21d forecast": view["fc21_vol"] * pts,
        "80% band": [("—" if pd.isna(lo) else f"{lo * pts:.0f}–{hi * pts:.0f}")
                     for lo, hi in zip(view["fc21_lo80"], view["fc21_hi80"])],
        "Earnings in": view["earn_days_to"],
    })
    num = lambda label, fmt="%.1f", **kw: st.column_config.NumberColumn(label, format=fmt, **kw)  # noqa: E731
    ui.table(table, hide_index=True, height=min(38 * (len(table) + 1), 560), column_config={
        "30d ATM": num("30d ATM", help="At-the-money implied vol, 30 days, in vol points"),
        "5d chg": num("5d chg", "%+.1f"),
        "1y pctile": st.column_config.ProgressColumn("1y pctile", format="percent", min_value=0, max_value=1,
                                                     help="Where 30d ATM vol sits in its trailing year (blank "
                                                          "until a year of history exists)"),
        "25d RR": num("25d RR", "%+.1f", help="25-delta call minus put vol: negative = puts richer (crash hedging)"),
        "30→91d slope": num("30→91d slope", "%+.1f", help="91d minus 30d ATM vol: negative = inverted (near-term stress)"),
        "VRP": num("VRP", "%+.1f", help="30d ATM implied minus 21d realised vol: options' premium over recent moves"),
        "21d forecast": num("21d forecast", help=f"Forecast realised vol over 21 trading days ({summary.get('model')})"),
        "Earnings in": num("Earnings in", "%d days"),
    })

# ================================================================= ticker detail
hist = load("history")
st.subheader("Ticker detail")
left, right = st.columns([1.5, 1])
with left, st.container(border=True):
    tickers = list(view["ticker"]) or list(ov["ticker"])
    tkr = st.selectbox("Ticker", tickers, key="vol_ticker", label_visibility="collapsed")
    h = hist[hist["ticker"] == tkr].set_index("date").sort_index() if hist is not None else pd.DataFrame()
    if not h.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=h.index, y=h["rv_cc_21d"] * 100, name="21d realised", mode="lines",
                                 line={"width": 2, "color": ui.PALETTE["grey"]},
                                 hovertemplate="%{x|%b %d}: %{y:.1f}<extra>realised</extra>"))
        fig.add_trace(go.Scatter(x=h.index, y=h["atm_30d"] * 100, name="30d implied (ATM)", mode="lines",
                                 line={"width": 2, "color": ui.PALETTE["teal"]},
                                 hovertemplate="%{x|%b %d}: %{y:.1f}<extra>implied</extra>"))
        fig.update_layout(height=260, margin={"l": 0, "r": 0, "t": 24, "b": 0}, hovermode="x unified",
                          legend={"orientation": "h", "y": 1.12, "x": 0}, yaxis={"ticksuffix": ""})
        ui.chart(fig, key="vol_hist")
        st.caption(f"{tkr}: implied vs realised vol, vol points. The gap between them is the variance risk premium.")

with right, st.container(border=True):
    st.markdown(f"**{tkr} ATM term structure**")
    row = ov[ov["ticker"] == tkr].iloc[0]
    tenors = {"7d": "atm_7d", "30d": "atm_30d", "91d": "atm_91d", "1y": "atm_365d"}
    ts = pd.Series({k: row[c] * 100 for k, c in tenors.items() if c in row and pd.notna(row[c])})
    if len(ts):
        fig = go.Figure(go.Scatter(x=list(ts.index), y=ts.values, mode="lines+markers", line={"width": 2},
                                   marker={"size": 8}, hovertemplate="%{x}: %{y:.1f}<extra></extra>"))
        fig.update_layout(height=230, margin={"l": 0, "r": 0, "t": 4, "b": 0}, showlegend=False)
        ui.chart(fig, key="vol_ts")
        st.caption(f"As of {pd.Timestamp(row['date']):%b %d}. Spot {row['spot']:,.2f}.")

# ================================================================= track record
rec = summary.get("track_record_21d") or {}
if rec:
    with st.expander("How good are the 21-day forecasts?"):
        rows = [{"Ticker": t, "Forecasts scored": r["n"], "RMSE, forecast": r.get("rmse_forecast"),
                 "RMSE, implied vol": r.get("rmse_implied"), "Bias, forecast": r.get("bias_forecast"),
                 "80% band hit rate": r.get("coverage80")} for t, r in rec.items() if r.get("n")]
        ui.table(pd.DataFrame(rows), hide_index=True, column_config={
            "RMSE, forecast": st.column_config.NumberColumn(format="%.1f pts"),
            "RMSE, implied vol": st.column_config.NumberColumn(format="%.1f pts"),
            "Bias, forecast": st.column_config.NumberColumn(format="%+.1f pts"),
            "80% band hit rate": st.column_config.NumberColumn(format="percent"),
        })
        st.caption("Scored against realised vol once each 21-day window has closed. Lower RMSE than implied vol "
                   "means the forecast beat the options market as a predictor; a well-calibrated band hits ~80%.")
