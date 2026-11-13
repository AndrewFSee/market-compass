"""Value & growth page: where S&P 500 sectors and stocks sit on cheapness and growth, from SEC
filings, and what a backtest of the scores found. Reads only what TickerLake publishes."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import store, ui
from modules.style import config as cfg

MODULE = cfg.MODULE


@st.cache_data(show_spinner=False)
def _cached(module: str, name: str, kind: str, stamp):
    return store.load_json(module, name) if kind == "json" else store.load_frame(module, name)


def load(name: str, kind: str = "frame"):
    return _cached(MODULE, name, kind, store.stamp(MODULE, name))


def short(sector: str) -> str:
    return cfg.SECTOR_SHORT.get(sector, sector)


def quadrant_lines(fig: go.Figure, span: float) -> None:
    """Zero lines and a label in each corner."""
    fig.add_hline(y=0, line_width=1, line_color=ui.PALETTE["grey"])
    fig.add_vline(x=0, line_width=1, line_color=ui.PALETTE["grey"])
    for x, y, text in [(1, 1, "cheap, growing"), (-1, 1, "pricey, growing"), (1, -1, "cheap, slow"),
                       (-1, -1, "pricey, slow")]:
        fig.add_annotation(x=x * span * 0.97, y=y * span * 0.97, text=text, showarrow=False,
                           xanchor="right" if x > 0 else "left", yanchor="top" if y > 0 else "bottom",
                           font={"size": 11, "color": ui.PALETTE["grey"]})


def stat(d: dict | None, digits: int = 3, unit: str = "") -> str:
    if not d or d.get("mean") is None:
        return "n/a"
    t = f" (t {d['t']:+.1f})" if d.get("t") is not None else ""
    return f"{d['mean']:+.{digits}f}{unit}{t}"


def halves(d: dict, digits: int = 3) -> str:
    if d.get("first") is None or d.get("second") is None:
        return "n/a"
    return f"{d['first']:+.{digits}f} / {d['second']:+.{digits}f}"


# ================================================================= header
st.title("Value & growth")
summary = load("summary", "json")
if not summary:
    st.info("No style scores yet. Run `python run_jobs.py --only style` from the hub folder (it runs TickerLake's "
            "`scripts/publish_style_to_hub.py`, which reads SEC filings, prices and members from the lake).")
    st.stop()

stocks, sectors, history = load("stocks"), load("sectors"), load("stock_history")
bt = summary.get("backtest") or {}
as_of = pd.Timestamp(summary["as_of"])
st.caption(f"As of {as_of:%b %d, %Y}: {summary['scored']} of {summary['members']} S&P 500 members scored from their "
           "SEC filings, prices and dividends. **Value** averages book, earnings, sales and dividends relative to price; "
           "**growth** averages the 3-year trend of EPS and of sales per share, capex / assets and return on assets. "
           "0 is the cap-weighted index; 1 is one standard deviation across members. Descriptive only: the backtest "
           "below found no forecasting power.")

# ================================================================= sectors
st.subheader("Sectors")
latest = sectors[sectors["date"] == sectors["date"].max()].set_index("sector")
month_ends = sorted(d for d in sectors["date"].unique() if d < sectors["date"].max())
then_date = month_ends[-cfg.PATH_MONTHS] if len(month_ends) >= cfg.PATH_MONTHS else None
then = sectors[sectors["date"] == then_date].set_index("sector") if then_date is not None else None

left, right = st.columns([4, 3])
with left:
    show_path = st.toggle(f"Show where each sector was {cfg.PATH_MONTHS} months ago", value=False,
                          disabled=then is None, key="style_path")
    span = max(0.6, float(np.nanmax(np.abs(latest[["value", "growth"]].to_numpy()))) * 1.25)
    if show_path and then is not None:
        span = max(span, float(np.nanmax(np.abs(then[["value", "growth"]].to_numpy()))) * 1.15)
    fig = go.Figure()
    if show_path and then is not None:
        for sec, r in latest.iterrows():
            if sec in then.index:
                fig.add_trace(go.Scatter(x=[then.at[sec, "value"], r["value"]], y=[then.at[sec, "growth"], r["growth"]],
                                         mode="lines+markers", showlegend=False, hoverinfo="skip",
                                         line={"width": 1.5, "color": ui.PALETTE["grey"]},
                                         marker={"size": [8, 0], "color": ui.PALETTE["grey"]}))
    size = 14 + 26 * np.sqrt(latest["mcap"] / latest["mcap"].max())
    fig.add_trace(go.Scatter(
        x=latest["value"], y=latest["growth"], mode="markers+text", text=[short(s) for s in latest.index],
        textposition="top center", showlegend=False,
        marker={"size": size, "color": cfg.COLORS["value"], "line": {"width": 2, "color": "rgba(0,0,0,0)"}, "opacity": 0.85},
        customdata=np.stack([latest.index, latest["stocks"], latest["mcap"] / 1e12], axis=1),
        hovertemplate="<b>%{customdata[0]}</b><br>value %{x:+.2f}, growth %{y:+.2f}<br>%{customdata[1]} stocks, "
                      "$%{customdata[2]:.1f}tn<extra></extra>"))
    quadrant_lines(fig, span)
    fig.update_layout(height=460, margin={"l": 0, "r": 0, "t": 10, "b": 0},
                      xaxis={"title": "value score (cheaper →)", "range": [-span, span], "zeroline": False},
                      yaxis={"title": "growth score (faster →)", "range": [-span, span], "zeroline": False})
    ui.chart(fig, key="style_sector_map", zoom=True)
    st.caption("Cap-weighted averages of each sector's stocks; marker size is the sector's market cap. Scroll to zoom, drag to pan, double-click to reset."
               + (f" Grey dots: {pd.Timestamp(then_date):%b %Y}." if show_path and then is not None else ""))

with right:
    tab = latest[["value", "growth"]].copy()
    if then is not None:
        tab["value_chg"] = tab["value"] - then["value"].reindex(tab.index)
        tab["growth_chg"] = tab["growth"] - then["growth"].reindex(tab.index)
    tab = tab.sort_values("value", ascending=False).reset_index()
    tab["sector"] = tab["sector"].map(short)
    fmt = st.column_config.NumberColumn
    ui.table(tab, hide_index=True, height=36 * (len(tab) + 1) + 4, column_config={
        "sector": "Sector", "value": fmt("Value", format="%+.2f"), "growth": fmt("Growth", format="%+.2f"),
        "value_chg": fmt("Δ value", format="%+.2f", help=f"Change over {cfg.PATH_MONTHS} months"),
        "growth_chg": fmt("Δ growth", format="%+.2f", help=f"Change over {cfg.PATH_MONTHS} months")})

# ================================================================= sector history
st.subheader("Sector history")
names = sorted(latest.index, key=short)
pick = st.selectbox("Sector", names, format_func=short, key="style_sector", label_visibility="collapsed")
h = sectors[sectors["sector"] == pick].sort_values("date")
fig = go.Figure()
for col, dash in (("value", "solid"), ("growth", "dash")):
    fig.add_trace(go.Scatter(x=h["date"], y=h[col], mode="lines", name=col.capitalize(),
                             line={"width": 2, "color": cfg.COLORS[col], "dash": dash},
                             hovertemplate=f"{col} %{{y:+.2f}}<extra></extra>"))
fig.add_hline(y=0, line_width=1, line_color=ui.PALETTE["grey"])
fig.update_layout(height=300, margin={"l": 0, "r": 0, "t": 10, "b": 0}, hovermode="x unified",
                  legend={"orientation": "h", "y": 1.08, "x": 0})
ui.chart(fig, key="style_sector_history")
st.caption(f"Month-ends since {pd.Timestamp(summary['history_start']):%b %Y} plus the latest session, each from that "
           "day's members and the filings known by then. Sectors are today's GICS labels.")

# ================================================================= stocks
st.subheader("Stocks")
c1, c2 = st.columns([2, 3])
with c1:
    sec_pick = st.selectbox("Sector", ["All sectors", *names], format_func=lambda s: s if s == "All sectors" else short(s),
                            key="style_stock_sector")
with c2:
    quads = st.multiselect("Quadrant", cfg.QUADRANTS, default=[], key="style_quadrant",
                           placeholder="All quadrants")
s = stocks.dropna(subset=["value", "growth"]).copy()
chosen = s if sec_pick == "All sectors" else s[s["sector"] == sec_pick]
if quads:
    chosen = chosen[chosen["quadrant"].isin(quads)]
others = s.drop(chosen.index)

fig = go.Figure()
if len(others):
    fig.add_trace(go.Scatter(x=others["value"], y=others["growth"], mode="markers", name="Other stocks",
                             marker={"size": 6, "color": ui.PALETTE["grey"], "opacity": 0.35},
                             customdata=others[["symbol", "name"]], hovertemplate="%{customdata[0]} %{customdata[1]}"
                             "<br>value %{x:+.2f}, growth %{y:+.2f}<extra></extra>"))
# label every selected stock once the selection is small enough to read when zoomed in
big = chosen if len(chosen) <= cfg.LABEL_ALL_UP_TO else chosen.nlargest(8, "mcap")
fig.add_trace(go.Scatter(x=chosen["value"], y=chosen["growth"], mode="markers", name="Selected",
                         marker={"size": 9, "color": cfg.COLORS["value"], "line": {"width": 1, "color": "white"}},
                         customdata=chosen[["symbol", "name"]], hovertemplate="<b>%{customdata[0]}</b> %{customdata[1]}"
                         "<br>value %{x:+.2f}, growth %{y:+.2f}<extra></extra>"))
fig.add_trace(go.Scatter(x=big["value"], y=big["growth"], mode="text", text=big["symbol"], textposition="top center",
                         showlegend=False, hoverinfo="skip", textfont={"size": 10}))
span = float(np.nanmax(np.abs(s[["value", "growth"]].to_numpy()))) * 1.05
quadrant_lines(fig, span)
fig.update_layout(height=480, margin={"l": 0, "r": 0, "t": 10, "b": 0}, showlegend=len(others) > 0,
                  legend={"orientation": "h", "y": 1.06, "x": 0},
                  xaxis={"title": "value score (cheaper →)", "range": [-span, span], "zeroline": False},
                  yaxis={"title": "growth score (faster →)", "range": [-span, span], "zeroline": False})
ui.chart(fig, key="style_stock_map", zoom=True)
quad = s["quadrant"].value_counts()
labelled = "all labelled" if len(big) == len(chosen) else "the 8 largest labelled (pick a sector to label all)"
st.caption(f"{len(chosen)} stocks selected, {labelled}. Scroll to zoom, drag to pan, double-click to reset. "
           "Across all scored members: "
           + ", ".join(f"{quad.get(q, 0)} {q}" for q in cfg.QUADRANTS)
           + ". Most sit cheaper and slower than 0 because 0 is the cap-weighted index, which a few large, "
           "fast-growing companies dominate.")

view = chosen.sort_values("mcap", ascending=False)
table = pd.DataFrame({"Symbol": view["symbol"], "Name": view["name"], "Sector": view["sector"].map(short),
                      "Cap $bn": view["mcap"] / 1e9, "Value": view["value"], "Growth": view["growth"],
                      "Quadrant": view["quadrant"]})
fcfg = {"Cap $bn": st.column_config.NumberColumn(format="%,.0f"),
        "Value": st.column_config.NumberColumn(format="%+.2f"), "Growth": st.column_config.NumberColumn(format="%+.2f")}
for col, (label, mult, unit) in cfg.FACTORS.items():
    name = f"{label} %" if unit else label
    table[name] = view[col] * mult
    fcfg[name] = st.column_config.NumberColumn(format="%.1f" if unit else "%.2f")
ui.table(table, hide_index=True, column_config=fcfg, height=360)

symbols = view["symbol"].tolist()
if symbols:
    sym = st.selectbox("History of one stock", symbols, key="style_symbol",
                       format_func=lambda x: f"{x}  {view.set_index('symbol').at[x, 'name'] or ''}")
    hs = history[history["symbol"] == sym].sort_values("date")
    now = view.set_index("symbol").loc[sym]
    hs = pd.concat([hs, pd.DataFrame([{"date": as_of, "symbol": sym, "value": now["value"], "growth": now["growth"]}])])
    fig = go.Figure()
    for col, dash in (("value", "solid"), ("growth", "dash")):
        fig.add_trace(go.Scatter(x=hs["date"], y=hs[col], mode="lines", name=col.capitalize(),
                                 line={"width": 2, "color": cfg.COLORS[col], "dash": dash},
                                 hovertemplate=f"{col} %{{y:+.2f}}<extra></extra>"))
    fig.add_hline(y=0, line_width=1, line_color=ui.PALETTE["grey"])
    fig.update_layout(height=260, margin={"l": 0, "r": 0, "t": 10, "b": 0}, hovermode="x unified",
                      legend={"orientation": "h", "y": 1.1, "x": 0})
    ui.chart(fig, key="style_stock_history")
    st.caption("Gaps are months without a recent filing, a usable share count or S&P 500 membership.")

# ================================================================= what it is / what it isn't
with st.expander("How the scores are built, and what the backtest found"):
    lines = [
        "- **Factors** (CRSP's style method, less the two that need analyst forecasts): value = book / price, "
        "trailing earnings / price, sales / price, dividend yield; growth = 3-year trend of EPS and of sales per share "
        "(slope of the last 12 trailing-year values, as a share of their average level), capex / assets, return on "
        "assets. Each factor is clipped at its 2.5 / 97.5 percentiles and standardised around the cap-weighted mean; "
        "a score needs at least two of its four factors.",
        "- **Point in time**: each number is the value first reported in a 10-Q / 10-K and counts from the day after "
        "the filing. Share counts are moved onto today's split basis; the latest date uses today's market caps"
        + (" from the Market job." if summary.get("caps_from_hub") else "."),
    ]
    if bt.get("stock"):
        st_v, st_g = bt["stock"]["value"], bt["stock"]["growth"]
        ts = [abs(x[h]["t"]) for x in (st_v, st_g) for h in ("1m", "3m") if x[h].get("t") is not None]
        fac = {f: d["1m"] for f, d in bt.get("factors", {}).items() if d["1m"].get("t") is not None}
        top = max(fac, key=lambda f: abs(fac[f]["t"])) if fac else None
        split = pd.Timestamp(bt["split"]).year
        verdict = ("neither score ranks future returns" if ts and max(ts) < 2
                   else "check the numbers: at least one stock-level test reached |t| ≥ 2")
        lines.append(
            f"- **Backtest, {pd.Timestamp(bt['start']):%b %Y}–{pd.Timestamp(bt['end']):%b %Y} ({bt['months']} month-ends, "
            f"{bt['members_min']}–{bt['members_max']} members with prices): {verdict}.** Rank correlation with the next "
            f"month's return: value {stat(st_v['1m'])}, growth {stat(st_g['1m'])}; before / after {split}: value "
            f"{halves(st_v['1m'])}, growth {halves(st_g['1m'])}. Next quarter (non-overlapping): value "
            f"{stat(st_v['3m'])}, growth {stat(st_g['3m'])}."
            + (f" Strongest single factor: {cfg.FACTORS[top][0].lower()} {stat(fac[top])}." if top else ""))
        q, c = bt.get("quintile", {}), bt.get("corner", {})
        if q:
            lines.append(f"- Top fifth minus bottom fifth, equal-weight, per month: value {stat(q['value'], 2, '%')}, "
                         f"growth {stat(q['growth'], 2, '%')}. Cheap-and-growing stocks ({c.get('share', 0):.0%} of the "
                         f"names) minus all, per month: {stat(c, 2, '%')}.")
        sec = bt.get("sector", {})
        if sec:
            sv, sg = sec["value"]["3m"], sec["growth"]["3m"]
            same = all(d.get("first") is not None and d.get("second") is not None
                       and np.sign(d["first"]) == np.sign(d["second"]) for d in (sv, sg))
            tilt = max(abs(sv.get("t") or 0), abs(sg.get("t") or 0))
            note = (" Both held their sign in each half, but with 11 sectors and one long trend (growth led most of "
                    "these years) that describes the period rather than a tested edge." if same and tilt >= 1.5
                    else " No reliable link.")
            lines.append(f"- By sector (cap-weighted, {bt.get('sectors', 11)} sectors), next quarter: value "
                         f"{stat(sv)}, growth {stat(sg)}.{note}")
    lines.append("- **Caveats**: sectors are today's GICS labels applied to the past, and members that have since left "
                 "the index have no sector, so sector averages and the sector test leave them out (stock-level tests "
                 "keep them); early years miss prices of some members that later left the index; the two analyst-forecast factors are left out until the daily "
                 "estimate snapshots (since Nov 2026) have history to test.")
    st.markdown("\n".join(lines))
