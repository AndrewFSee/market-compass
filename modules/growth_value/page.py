"""Growth vs value page: the investment-gap timing signal (Ken French's large growth / large value
portfolios since 1926, plus a live version from S&P 500 members' SEC filings) and what its backtest
found. Reads only what the growth_value job publishes."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import store, ui
from modules.growth_value import config as cfg

MODULE = cfg.MODULE


@st.cache_data(show_spinner=False)
def _cached(module: str, name: str, kind: str, stamp):
    return store.load_json(module, name) if kind == "json" else store.load_frame(module, name)


def load(name: str, kind: str = "frame"):
    return _cached(MODULE, name, kind, store.stamp(MODULE, name))


def pct_yr(d: dict | None, key: str = "excess", t: str = "t") -> str:
    if not d or d.get(key) is None:
        return "n/a"
    return f"{d[key]:+.1f}%/yr (t {d[t]:.1f})" if d.get(t) is not None else f"{d[key]:+.1f}%/yr"


def period_label(d: dict | None) -> str:
    return f"{d['start'][:4]}–{d['end'][:4]}" if d and d.get("start") else "n/a"


def fmt_z(z) -> str:
    return "n/a" if z is None or (isinstance(z, float) and np.isnan(z)) else f"{z:+.2f}"


# ================================================================= header
st.title("Growth vs value")
summary = load("summary", "json")
if not summary:
    st.info("No growth / value data yet. Run `python run_jobs.py --only growth_value` from the hub folder (it downloads "
            "Ken French's portfolio file; run the style job first for the live reading from SEC filings).")
    st.stop()

hist, annual, live = load("history"), load("annual"), load("live")
now, rule, ann, lv = summary["now"], summary["rule"], summary["annual"], summary.get("live") or {}
lag = summary["settings"]["realistic_lag"]
as_of = pd.Timestamp(summary["as_of"])
st.caption("When growth companies have been expanding their assets much faster than value companies, compared with "
           "the past, value has tended to beat growth over the next year. This page tracks that gap between the "
           "large growth and large value portfolios of Ken French's data library (book / price below the 30th / above "
           "the 70th percentile), and a live version built from S&P 500 members' SEC filings. "
           "It is a research signal, not advice: see the test results and caveats below.")

# ================================================================= the reading now
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.metric("Signal (French data)", now["signal"].upper(), help="Value when the investment-gap z-score is above "
              f"{summary['settings']['threshold']:g} (growth companies out-investing value companies by more than "
              "usual), growth otherwise")
    st.caption(f"{as_of:%b %Y} reading; this side since {pd.Timestamp(now['since']):%b %Y}")
with c2:
    if lv.get("available") and lv.get("usable"):
        lead = (lv.get("calibration") or {}).get("lead", 12)
        st.metric("Early estimate (SEC filings)", lv["signal"].upper(),
                  help=f"S&P 500 members' gap from their latest filings, put on French's scale by regressing French's "
                       f"gap {lead} months later on it. An estimate of where French's reading is heading, not the "
                       "backtested signal.")
        st.caption(f"As of {pd.Timestamp(lv['as_of']):%b %d, %Y}; z {lv['z']:+.2f}"
                   + ("" if lv.get("tracking") else f" (loose: {lv['reason']})"))
    elif lv.get("available"):
        st.metric("Early estimate (SEC filings)", "n/a")
        st.caption(f"Not enough history: {lv.get('reason')}")
    else:
        st.metric("Early estimate (SEC filings)", "n/a")
        st.caption("Run the style job (TickerLake) for it")
with c3:
    st.metric("Investment gap z", fmt_z(now["z_inv"]))
    st.caption(f"Asset growth: growth {now['inv_g'] * 100:.1f}%, value {now['inv_v'] * 100:.1f}%")
with c4:
    st.metric("Value spread z", fmt_z(now["z_vs"]))
    st.caption(f"Profitability gap z {fmt_z(now['z_op'])}")

# ================================================================= history of the gap
st.subheader("Investment gap")
h = hist.dropna(subset=["z_inv"])
fig = go.Figure()
fig.add_trace(go.Scatter(x=h["date"], y=h["z_inv"], mode="lines", name="French (z vs all earlier months)",
                         line={"width": 2, "color": cfg.COLORS["value"]},
                         hovertemplate="%{x|%b %Y}: z %{y:+.2f}<extra></extra>"))
if live is not None and "z_mapped" in live and live["z_mapped"].notna().any():
    fig.add_trace(go.Scatter(x=live["month"], y=live["z_mapped"], mode="lines", name="Live from SEC filings (on French's scale)",
                             line={"width": 2, "color": cfg.COLORS["live"], "dash": "dash"},
                             hovertemplate="%{x|%b %Y}: z %{y:+.2f}<extra></extra>"))
fig.add_hline(y=summary["settings"]["threshold"], line_width=1, line_color=ui.PALETTE["grey"])
fig.add_annotation(x=0.01, y=1, xref="paper", yref="paper", text="above the line: hold value", showarrow=False,
                   xanchor="left", yanchor="top", font={"size": 11, "color": ui.PALETTE["grey"]})
fig.add_annotation(x=0.01, y=0, xref="paper", yref="paper", text="below: hold growth", showarrow=False,
                   xanchor="left", yanchor="bottom", font={"size": 11, "color": ui.PALETTE["grey"]})
fig.update_layout(height=320, margin={"l": 0, "r": 0, "t": 10, "b": 0}, hovermode="x unified",
                  legend={"orientation": "h", "y": 1.1, "x": 0}, yaxis={"title": "z-score"})
ui.chart(fig, key="gv_gap")
st.caption("Growth minus value asset growth (value-weighted, fiscal year t-1 vs t-2, new each July), as a z-score "
           f"against every earlier month (needs {summary['settings']['z_min_months'] // 12} years, so from the 1970s). "
           "French posts each July's numbers around October.")

# ================================================================= backtest
st.subheader("Backtest")
b = hist.dropna(subset=["rule_ret", "blend_ret"])
b = b[b["date"] >= pd.Timestamp(f"{summary['periods'][-1][0]}-01-01")]
fig = go.Figure()
for col, name, color, dash in (("rule_ret", "Acting at once", cfg.COLORS["rule"], "solid"),
                               ("rule_late_ret", f"Acting {lag} months late", cfg.COLORS["late"], "dash")):
    x = b.dropna(subset=[col])
    rel = (1 + x[col]).cumprod() / (1 + x["blend_ret"]).cumprod()
    fig.add_trace(go.Scatter(x=x["date"], y=rel, mode="lines", name=name, line={"width": 2, "color": color, "dash": dash},
                             hovertemplate="%{x|%b %Y}: %{y:.2f}× the 50/50 mix<extra></extra>"))
fig.add_hline(y=1, line_width=1, line_color=ui.PALETTE["grey"])
fig.update_layout(height=320, margin={"l": 0, "r": 0, "t": 10, "b": 0}, hovermode="x unified",
                  legend={"orientation": "h", "y": 1.1, "x": 0}, yaxis={"title": "vs 50/50 growth/value", "type": "log"})
ui.chart(fig, key="gv_backtest")
st.caption(f"Growth of the rule relative to a 50/50 mix of French's large growth and large value portfolios, "
           f"{summary['settings']['cost_bp']:.0f} bp per switch.")
with st.container():
    rows = []
    labels = [period_label(d) for d in rule["0"]]
    for key, name in [*[(str(l), "at once" if l == 0 else f"{l} months late") for l in summary["lags"]],
                      ("yearly", f"once a year, {lag} months late")]:
        r = rule[key]
        rows.append({"Acting": name, **{lab: pct_yr(d) for lab, d in zip(labels, r)},
                     "Switches / yr": r[-1].get("switches_per_year")})
    ui.table(pd.DataFrame(rows), hide_index=True, column_config={
        "Switches / yr": st.column_config.NumberColumn(format="%.2f")})
t2, _ = st.columns([3, 2])
with t2:
    etf = summary.get("etf") or []
    if etf:
        ui.table(pd.DataFrame([{"ETFs": e["pair"], "Acting": "at once" if e["lag"] == 0 else f"{e['lag']} months late",
                                "Since": e.get("start", "")[:7], "vs 50/50": pct_yr(e)} for e in etf]), hide_index=True)
    st.caption("Excess return over the 50/50 mix, %/yr, with Newey-West t-statistics. The ETF rows apply the "
               "French-based position to the ETFs.")


# ================================================================= one reading a year
st.subheader("Each July")
a = annual.dropna(subset=["z_inv"]).sort_values("year", ascending=False).head(30)
tab = pd.DataFrame({"Year": a["year"].astype(str), "Growth asset growth %": a["inv_g"] * 100,
                    "Value asset growth %": a["inv_v"] * 100, "Gap z": a["z_inv"],
                    "Says": np.where(a["z_inv"] > summary["settings"]["threshold"], "value", "growth"),
                    "Next 12 months: value minus growth %": a["next_12m"] * 100})
fmt = st.column_config.NumberColumn
ui.table(tab, hide_index=True, height=360, column_config={
    "Growth asset growth %": fmt(format="%.1f"), "Value asset growth %": fmt(format="%.1f"), "Gap z": fmt(format="%+.2f"),
    "Next 12 months: value minus growth %": fmt(format="%+.1f", help="Log return, August to July; None until the 12 months are complete")})

# ================================================================= live version
if lv.get("available") and live is not None:
    st.subheader("Live version from SEC filings")
    cal = lv.get("calibration") or {}
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=live["month"], y=live["ag_gap"] * 100, mode="lines", name="S&P 500 members (SEC filings)",
                             line={"width": 2, "color": cfg.COLORS["live"], "dash": "dash"},
                             hovertemplate="%{x|%b %Y}: %{y:+.1f} pts<extra></extra>"))
    lead = cal.get("lead", 12)
    fig.add_trace(go.Scatter(x=live["month"], y=live["french_inv_gap_ahead"] * 100, mode="lines",
                             name=f"French, {lead} months later",
                             line={"width": 2, "color": cfg.COLORS["value"]},
                             hovertemplate="%{x|%b %Y}: %{y:+.1f} pts<extra></extra>"))
    fig.add_hline(y=0, line_width=1, line_color=ui.PALETTE["grey"])
    fig.update_layout(height=280, margin={"l": 0, "r": 0, "t": 10, "b": 0}, hovermode="x unified",
                      legend={"orientation": "h", "y": 1.12, "x": 0}, yaxis={"title": "growth minus value, pts"})
    ui.chart(fig, key="gv_live")
    corr = cal.get("corr")
    st.caption(
        f"Asset growth over the last four quarters, growth members minus value members (lowest / highest 30% book / "
        f"price, {lv['growth_n']} and {lv['value_n']} stocks, cap-weighted; {lv['cover']:.0%} of each side's cap has "
        f"the data). Latest: growth {lv['growth_ag'] * 100:.1f}%, value {lv['value_ag'] * 100:.1f}%. "
        + (f"Correlation with French's gap {lead} months later: {corr:+.2f} over {cal['n']} month-ends "
           f"({cal['start'][:7]} to {cal['end'][:7]}); same month only {lv.get('corr_same_month', float('nan')):+.2f}, "
           "because French's figure is fixed each July from the fiscal year before. " if corr is not None else "")
        + (f"By side: growth {lv['corr_growth_side']:+.2f}, value {lv['corr_value_side']:+.2f} (a different "
           "universe: S&P 500 members rather than all large US stocks). " if lv.get("corr_growth_side") is not None
           and lv.get("corr_value_side") is not None else "")
        + "It updates with every 10-Q, but it exists only since 2012 and was not "
          "tested on its own, so the evidence for the signal comes from French's history.")

# ================================================================= what the test found
with st.expander("How it's built, and what the test found"):
    full, first, second = rule["0"][-1], rule["0"][0], rule["0"][1]
    late = rule[str(lag)][-1]
    ai = ann["inv"]
    dec = summary.get("decades") or {}
    pos_dec = sum(1 for v in dec.values() if v is not None and v > 0)
    lines = [
        "- **Data**: Ken French's 2x3 portfolios by size and book / market, value-weighted, large caps only. Book / "
        "price is French's June figure updated each month with the portfolio's return since; asset growth and "
        "operating profitability are for the fiscal year before each June and count from July. z-scores use only "
        f"earlier months. French data through {summary.get('data_through') or summary['as_of'][:7]}.",
        f"- **One reading a year** (each July, then value minus growth over the next 12 months), "
        f"{ai['all'].get('start')}–{ai['all'].get('end')}: {ai['all'].get('slope', float('nan')):+.1f} pts per standard "
        f"deviation of the gap (t {ai['all'].get('t', float('nan')):.1f}, rank corr {ai['all'].get('rank_corr', float('nan')):+.2f}); "
        f"before / from 2000: t {ai['first'].get('t', float('nan')):.1f} / {ai['second'].get('t', float('nan')):.1f}; "
        f"without the dot-com years ({cfg.EXCLUDE_BUBBLE[0]}–{cfg.EXCLUDE_BUBBLE[1]}): t {ai['no_bubble'].get('t', float('nan')):.1f}; "
        f"rank correlation positive in {pos_dec} of {len(dec)} decades.",
        f"- **The rule** (value when the gap's z-score is above {summary['settings']['threshold']:g}, growth otherwise; "
        f"{summary['settings']['cost_bp']:.0f} bp per switch): "
        f"{pct_yr(full)} over the 50/50 mix {period_label(full)}; {pct_yr(first)} {period_label(first)}, "
        f"{pct_yr(second)} {period_label(second)}. Against a fixed mix with the same average growth share "
        f"({full.get('share_growth', 0):.0%}): {pct_yr(full, 'timing', 't_timing')}, so it is timing, not just a value tilt.",
        f"- **Acting late costs a lot**: {lag} months late (when French's July data appears) {pct_yr(late)}; "
        f"switching once a year {pct_yr(rule['yearly'][-1])}. The SEC-based version avoids most of that delay.",
        f"- **Other readings, same rule**: profitability gap (growth when growth is unusually more profitable) "
        f"{pct_yr(summary['others']['op'][-1])}; value spread (value when value is unusually cheap) "
        f"{pct_yr(summary['others']['vs'][-1])}.",
        f"- **Caveats**: this was the best of about {summary['settings']['tries']} growth / value timing ideas tried "
        "(price trends, mean reversion, Kalman filters, macro rules and machine learning showed nothing that survived), "
        "so expect less than the backtest; one decision a year means few independent tests; French's portfolios are "
        "more extreme than growth / value ETFs, and the ETF history is about 20 years; French revises past data "
        "occasionally. The live version uses today's S&P 500 members' filings with a different asset-growth window "
        "(four quarters, not fiscal years) and has not been tested on its own.",
    ]
    st.markdown("\n".join(lines))
