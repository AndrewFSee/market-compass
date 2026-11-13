"""Market Environment page. Reads only from the hub data folder."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from core import store, ui
from modules.market import config as cfg

MODULE = cfg.MODULE


@st.cache_data(show_spinner=False)
def _cached(name: str, kind: str, stamp):
    return store.load_json(MODULE, name) if kind == "json" else store.load_frame(MODULE, name)


def load(name: str, kind: str = "frame"):
    return _cached(name, kind, store.stamp(MODULE, name))


@st.cache_data(show_spinner=False)
def _cached_other(module: str, name: str, kind: str, stamp):
    return store.load_json(module, name) if kind == "json" else store.load_frame(module, name)


def load_other(module: str, name: str, kind: str = "frame"):
    """Another module's output (here: what TickerLake's publisher wrote)."""
    return _cached_other(module, name, kind, store.stamp(module, name))


def _fmt(v, digits=2):
    return "—" if v is None or pd.isna(v) else f"{v:,.{digits}f}"


def trend_text(g: dict) -> str:
    """'**Falling** · ▼ 4.7 vs 1 week ago (30.2) · ▼ 33.5 vs 1 month ago (59.0)'."""
    trend = g.get("trend") or {}
    if not trend:
        return ""
    flat = (g["hi"] - g["lo"]) * 0.02  # moves under 2% of the scale count as flat
    parts, signs = [], []
    for label, t in trend.items():
        d = t["change"]
        sign = 0 if abs(d) < flat else (1 if d > 0 else -1)
        signs.append(sign)
        arrow = {1: "▲", -1: "▼", 0: "≈"}[sign]
        prior = f"{t['prior']:.1f}".replace("-", "−")
        parts.append(f"{arrow} {abs(d):.1f} vs {label} ago ({prior})")
    word = ("Rising" if all(x > 0 for x in signs) else "Falling" if all(x < 0 for x in signs)
            else "Flat" if all(x == 0 for x in signs) else "Mixed")
    return f"**{word}** · " + " · ".join(parts)


def _mid(g: dict, band: int) -> float:
    """A value inside `band`, to name it with the gauge's own labels."""
    edges = [g["lo"], *g["cuts"], g["hi"]]
    return (edges[band] + edges[band + 1]) / 2


def band_names(cuts: list[float]) -> list[str]:
    edges = [f"{c:g}".replace("-", "\u2212") for c in cuts]
    return [f"below {edges[0]}", *(f"{a} to {b}" for a, b in zip(edges[:-1], edges[1:])), f"above {edges[-1]}"]


def with_spy_figure(h: pd.DataFrame, g: dict, key: str, height: int = 300) -> go.Figure:
    """Gauge on top, S&P 500 below, sharing the date axis (two panels, not two y-axes)."""
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.06, row_heights=[0.58, 0.42])
    fig.add_trace(go.Scatter(x=h.index, y=h[key], mode="lines", line={"width": 2, "color": ui.PALETTE["teal"]},
                             name=g["title"], hovertemplate="%{y:.1f}<extra>" + g["title"] + "</extra>"),
                  row=1, col=1)
    fig.add_trace(go.Scatter(x=h.index, y=h["spy"], mode="lines", line={"width": 2, "color": ui.PALETTE["grey"]},
                             name="S&P 500 (SPY)", hovertemplate="%{y:,.2f}<extra>SPY</extra>"), row=2, col=1)
    for c in g["cuts"]:
        fig.add_hline(y=c, line_dash="dot", line_width=1, opacity=0.5, row=1, col=1)
    fig.update_yaxes(range=[g["lo"], g["hi"]], row=1, col=1)
    fig.update_yaxes(title={"text": "SPY", "font": {"size": 11}}, row=2, col=1)
    fig.update_layout(height=height, margin={"l": 0, "r": 0, "t": 4, "b": 0}, showlegend=False,
                      hovermode="x unified")
    return fig


# ================================================================= header
st.title("Market Environment")
meta = load("meta", "json")
if not meta:
    st.info("No market data yet. In the project folder run `python run_jobs.py` "
            "(or `python run_jobs.py --demo` to try it with synthetic data), then refresh this page.")
    st.stop()

if meta.get("demo"):
    st.warning("Showing **synthetic demo data**. Run `python run_jobs.py` to load real market data.")
st.caption(f"Prices through {meta['as_of']} · refreshed {meta['run_at_local']}")
if meta.get("missing"):
    with st.expander(f"{len(meta['missing'])} inputs could not be loaded on the last run"):
        st.write(", ".join(meta["missing"]))

# ================================================================= gauges
st.subheader("Regime, liquidity & sentiment")
gauges = load("gauges", "json") or {}
history = load("gauge_history")
econ_history = load("econ_history")

cols = st.columns(4)
for col, key in zip(cols, cfg.GAUGES):
    g = gauges.get(key)
    if not g:
        continue
    with col, st.container(border=True):
        band = ui.band_index(g["value"], g["cuts"])
        color = g["colors"][band] if band is not None else "grey"
        st.markdown(f"**{g['title']}**")
        ui.badge(g["label"], color)
        ui.chart(ui.gauge(g["value"], g["lo"], g["hi"], g["cuts"], g["colors"]), key=f"gauge_{key}")
        if trend_text(g):
            st.markdown(trend_text(g))
        st.caption(g["caption"])
        if g.get("date"):
            st.caption(f"Reading for {g['date']}")

        with st.expander("Components"):
            comp = pd.DataFrame(g["components"])
            if not comp.empty:
                col_cfg = {"component": "Component", "reading": st.column_config.NumberColumn("Reading", format="%.2f"),
                           "score": st.column_config.NumberColumn("Score", format="%.1f"), "as_of": "As of"}
                if "weight" in comp:
                    col_cfg["weight"] = st.column_config.NumberColumn("Weight", format="percent")
                    comp = comp.sort_values("weight", ascending=False)
                ui.table(comp, hide_index=True, column_config=col_cfg)

        with st.expander("History vs S&P 500"):
            h = (econ_history if key == "economic" else history)
            years = 10 if key == "economic" else 2
            if h is not None and key in h and "spy" in h:
                h = h[[key, "spy"]].dropna(subset=[key])
                h = h[h.index >= h.index.max() - pd.DateOffset(years=years)]
                ui.chart(with_spy_figure(h, g, key), key=f"hist_{key}")
                link = g.get("vs_spy")
                if link and link.get("coincident") is not None:
                    st.caption(f"Moves with the market: r = {link['coincident']:+.2f} "
                               "(see *Gauges vs the S&P 500* below).")

# ================================================================= gauges vs market
links = {k: g["vs_spy"] for k, g in gauges.items() if g.get("vs_spy")}
if links:
    st.subheader("Gauges vs the S&P 500")
    with st.container(border=True):
        rows = []
        for k, link in links.items():
            p = link.get("predictive")
            if p is None:
                verdict = "too little history"
            elif link["significant"]:
                verdict = "higher reading → better returns" if p > 0 else "higher reading → worse returns"
            else:
                verdict = "no reliable signal"
            rows.append({"Gauge": gauges[k]["title"], "Moves with market": link.get("coincident"),
                         "Next period": link["horizon_label"], "Next-period link": p,
                         "Periods": link.get("n_predictive"), "Since": link["start"][:7], "Verdict": verdict})
        ui.table(pd.DataFrame(rows), hide_index=True, column_config={
            "Moves with market": st.column_config.NumberColumn(
                format="%+.2f", help="Correlation of the gauge's change with the S&P 500's return over the same "
                                     "period. Near +1: it mostly tracks the market."),
            "Next-period link": st.column_config.NumberColumn(
                format="%+.2f", help="Rank correlation of the gauge's reading with the S&P 500's return over the "
                                     "following period, using each reading only once it was published."),
            "Periods": st.column_config.NumberColumn(format="%d", help="Independent (non-overlapping) periods"),
        })
        st.caption("Both measures use non-overlapping periods, so 'Periods' is the real sample size. A link counts "
                   "as reliable when |link| × √(periods − 1) > 1.96 (95%); with four gauges tested, one false "
                   "positive is not unusual.")

        names = {gauges[k]["title"]: k for k in links}
        pick = names[ui.choice("Gauge", list(names), key="vs_spy_gauge")]
        g, link = gauges[pick], links[pick]
        span = link["horizon_label"].replace("-", " ")
        st.markdown(f"**{g['title']}: S&P 500 return over the following {span}, by reading**")
        bands = band_names(g["cuts"])
        table = [{"Reading": f"{bands[b['band']]} ({cfg.gauge_label(pick, _mid(g, b['band'])).lower()})",
                  "Avg S&P return": b["mean"], "Share positive": b["hit"], "Periods": b["periods"]}
                 for b in link["bands"]]
        table.append({"Reading": "all readings", "Avg S&P return": link["overall"]["mean"],
                      "Share positive": link["overall"]["hit"], "Periods": link["overall"]["periods"]})
        ui.table(pd.DataFrame(table), hide_index=True, column_config={
            "Avg S&P return": st.column_config.NumberColumn(format="%+.2f%%"),
            "Share positive": st.column_config.NumberColumn(format="percent"),
            "Periods": st.column_config.NumberColumn(
                format="%.0f", help="Days (or months) in the band ÷ period length: the effective number of "
                                    "independent periods. Under ~20 is mostly noise."),
        })
        lag, unit = link.get("lag", 0), ("month" if pick == "economic" else "trading day")
        note = f"Since {link['start'][:7]}."
        if lag:
            note += f" Each reading is used {lag} {unit}{'s' if lag != 1 else ''} after its date, once published."
        if pick == "economic":
            note += (" Its history uses today's revised data and indicator weights fitted on the whole sample, "
                     "so it flatters the gauge.")
        st.caption(note)

# ================================================================= headline economy
def headline_value(item: dict) -> str:
    v, unit = item["value"], item["unit"]
    if item["kind"] == "range" and item.get("low") is not None:
        return f"{item['low']:.2f}–{v:.2f}%"
    if unit == "k":
        return f"{v:+,.0f}k"
    if unit == "pts":
        return f"{v:+.2f} pts"
    return f"{v:.2f}%" if item["freq"] == "daily" else f"{v:.1f}%"


def headline_period(item: dict) -> str:
    d = pd.Timestamp(item["date"])
    if item["freq"] == "quarterly":
        return f"Q{d.quarter} {d.year}"
    return f"{d:%b %Y}" if item["freq"] == "monthly" else f"{d:%b %d}"


def next_release(key: str | None, calendar: pd.DataFrame | None):
    if not key or calendar is None or calendar.empty:
        return None
    today = pd.Timestamp.today().normalize()
    dates = pd.to_datetime(calendar.loc[calendar["release_key"] == key, "release_date"])
    dates = dates[dates >= today]
    return dates.min() if len(dates) else None


st.subheader("Economy at a glance")
headline = (load("headline_econ", "json") or {}).get("items") or []
shown = [h for h in headline if h.get("value") is not None]
if not shown:
    st.info("No headline economic data yet (FRED). Rerun the market job.")
else:
    calendar = load_other("events", "calendar")
    cols = st.columns(3)
    for i, h in enumerate(shown):
        prev = "1 month ago" if h["freq"] == "daily" else ("prior quarter" if h["freq"] == "quarterly"
                                                          else "prior month")
        digits = 0 if h["unit"] == "k" else (2 if h["freq"] == "daily" or h["unit"] == "pts" else 1)
        unit = "k" if h["unit"] == "k" else " pts"  # changes in a rate are percentage points
        delta = None if h.get("change") is None else f"{h['change']:+,.{digits}f}{unit} vs {prev}"
        nxt = next_release(h.get("release"), calendar)
        flat = h.get("change") is not None and abs(h["change"]) < 1e-9
        color = "off" if flat else {True: "normal", False: "inverse"}.get(h.get("up_is_good"), "off")
        if flat:
            delta = f"unchanged vs {prev}"
        with cols[i % 3]:
            st.metric(f"{h['label']} · {headline_period(h)}", headline_value(h), delta=delta, delta_color=color,
                      delta_arrow="off" if flat else "auto",
                      chart_data=h.get("spark"), chart_type="line", border=True,
                      help=(f"Next release {nxt:%a %b %d}" if nxt is not None else "No release date in the calendar")
                      + f". FRED {h['kind']} of the latest {h['freq']} figure.")
    st.caption("Latest published figures from FRED (CPI and PCE are year-over-year; GDP is the latest quarter's "
               "growth at an annual rate; payrolls are the monthly change). Hover a tile for its next release date "
               "from the Events calendar. Lines show the last two years.")

# ================================================================= breadth & style
st.subheader("Breadth & style")
left, right = st.columns([1, 1.2])
breadth_by = {"NYSE": load_other("breadth", "nyse"), "S&P 500": load("breadth")}
breadth_by = {k: v for k, v in breadth_by.items() if v is not None and not v.empty}

with left, st.container(border=True):
    t, c = st.columns([1.3, 1], vertical_alignment="center")
    t.markdown("**Market breadth**")
    with c:
        universe = ui.choice("Universe", list(breadth_by) or ["S&P 500"], key="breadth_universe")
    breadth = breadth_by.get(universe)
    if breadth is None:
        st.info("No breadth data.")
    else:
        last = breadth.iloc[-1]
        prev = breadth.iloc[-6] if len(breadth) > 5 else breadth.iloc[0]
        tabs = st.tabs(["Adv / Dec", "Above 20-day", "Above 50-day", "Above 200-day", "52-wk highs/lows"])
        with tabs[0]:
            a, mid, b = st.columns([1, 2, 1], vertical_alignment="center")
            a.metric("Advancing", f"{last.pct_adv:.0f}%", f"{last.pct_adv - prev.pct_adv:+.1f} (5d)")
            with mid:
                ui.chart(ui.donut(["Advancing", "Declining", "Unchanged"],
                                  [last.advancing, last.declining, last.unchanged],
                                  ["teal", "red", "amber"]), key="donut_ad")
            b.metric("Declining", f"{last.pct_dec:.0f}%", f"{last.pct_dec - prev.pct_dec:+.1f} (5d)",
                     delta_color="inverse")
            ad = breadth["ad_line"].iloc[-252:]
            fig = go.Figure(go.Scatter(x=ad.index, y=ad.values, mode="lines", line={"width": 1.6},
                                       hovertemplate="%{x|%b %d}: %{y:,.0f}<extra></extra>"))
            fig.update_layout(height=170, margin={"l": 0, "r": 0, "t": 22, "b": 0},
                              title={"text": "Cumulative A/D line, 1 year", "font": {"size": 13}})
            ui.chart(fig, key="ad_line")
        for tab, n in zip(tabs[1:4], (20, 50, 200)):
            with tab:
                col = f"above_{n}"
                a, mid, b = st.columns([1, 2, 1], vertical_alignment="center")
                a.metric(f"Above {n}-day", f"{last[col]:.0f}%", f"{last[col] - prev[col]:+.1f} (5d)")
                with mid:
                    ui.chart(ui.donut([f"Above {n}-day", f"Below {n}-day"], [last[col], 100 - last[col]],
                                      ["teal", "red"]), key=f"donut_{n}")
                b.metric(f"Below {n}-day", f"{100 - last[col]:.0f}%", f"{prev[col] - last[col]:+.1f} (5d)",
                         delta_color="inverse")
                s = breadth[col].iloc[-252:]
                fig = go.Figure(go.Scatter(x=s.index, y=s.values, mode="lines", line={"width": 1.6},
                                           hovertemplate="%{x|%b %d}: %{y:.0f}%<extra></extra>"))
                fig.update_layout(height=170, margin={"l": 0, "r": 0, "t": 22, "b": 0}, yaxis={"range": [0, 100]},
                                  title={"text": f"% above {n}-day average, 1 year", "font": {"size": 13}})
                ui.chart(fig, key=f"above_{n}_hist")
        with tabs[4]:
            a, b = st.columns(2)
            a.metric("New 52-wk highs", int(last.new_highs), f"{int(last.new_highs - prev.new_highs):+d} (5d)")
            b.metric("New 52-wk lows", int(last.new_lows), f"{int(last.new_lows - prev.new_lows):+d} (5d)",
                     delta_color="inverse")
            hl = breadth[["new_highs", "new_lows"]].iloc[-126:]
            fig = go.Figure([
                go.Bar(x=hl.index, y=hl.new_highs, name="New highs", marker_color=ui.PALETTE["teal"]),
                go.Bar(x=hl.index, y=-hl.new_lows, name="New lows", marker_color=ui.PALETTE["red"],
                       customdata=hl.new_lows, hovertemplate="%{x|%b %d}: %{customdata}<extra>New lows</extra>"),
            ])
            fig.update_layout(height=230, barmode="relative", margin={"l": 0, "r": 0, "t": 10, "b": 0},
                              legend={"orientation": "h", "y": 1.1})
            ui.chart(fig, key="highs_lows")
        if universe == "NYSE":
            prov = int(last.get("provisional", 0) or 0)
            st.caption(f"All {int(last.stocks):,} NYSE common stocks (ADRs, REITs and closed-end funds included; "
                       f"preferreds, notes and ETFs not), as of {breadth.index[-1]:%b %d, %Y}."
                       + (f" {prov:,} of the latest closes are provisional (last trade before 4 PM), replaced "
                          "by the official close the next evening." if prov else "")
                       + " History before collection began covers only stocks still listed, which flatters "
                         "it a little.")
        else:
            st.caption(f"S&P 500 members, as of {breadth.index[-1]:%b %d, %Y}. Large caps only: their breadth "
                       "runs well above the NYSE's in a market led by big stocks.")

etf_returns = load("etf_returns")
with right, st.container(border=True):
    st.markdown("**Style / size grid**")
    style_tf = ui.choice("Timeframe", cfg.TIMEFRAMES, key="style_tf")
    items = []
    for size, row in cfg.STYLE_GRID.items():
        for style, ticker in row.items():
            v = etf_returns.at[ticker, style_tf] if etf_returns is not None and ticker in etf_returns.index else None
            items.append((f"{size} {style}", ticker, v))
    ui.tiles(items, cfg.FLAT_BAND[style_tf], columns=3)
    st.caption("Rows: large, mid, small caps · Columns: value, core, growth")

# ================================================================= sectors / factors
st.subheader("Sector & factor performance")
with st.container(border=True):
    c1, c2, c3 = st.columns([1, 1, 2.2], vertical_alignment="center")
    with c1:
        group = ui.choice("Group", ["Sectors", "Factors"], key="sf_group")
    with c2:
        order = ui.choice("Order", ["Performance", "A–Z"], key="sf_order")
    with c3:
        sf_tf = ui.choice("Timeframe", cfg.TIMEFRAMES, key="sf_tf")
    names = dict(cfg.SECTORS) if group == "Sectors" else dict(cfg.FACTORS)
    if group == "Sectors":
        names[cfg.BENCHMARK] = "S&P 500 (benchmark)"
    rows = [(name, t, etf_returns.at[t, sf_tf] if etf_returns is not None and t in etf_returns.index else None)
            for t, name in names.items()]
    if order == "Performance":
        rows.sort(key=lambda r: -1e9 if r[2] is None or pd.isna(r[2]) else r[2], reverse=True)
    else:
        rows.sort(key=lambda r: r[0])
    ui.tiles(rows, cfg.FLAT_BAND[sf_tf], columns=4)

# ================================================================= rotation map
QUAD_COLORS = {"Leading": ui.PALETTE["teal"], "Weakening": ui.PALETTE["amber"], "Lagging": ui.PALETTE["red"],
               "Improving": "#5B8DEF"}
QUAD_ORDER = list(QUAD_COLORS)  # clockwise from top right, as in indicators.QUADRANTS
ARROWS = "→↗↑↖←↙↓↘"


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[:2], 16)},{int(h[2:4], 16)},{int(h[4:], 16)},{alpha})"


def heading(dx, dy) -> str:
    if dx is None or dy is None or pd.isna(dx) or pd.isna(dy):
        return ""
    return ARROWS[int(((np.degrees(np.arctan2(dy, dx)) + 22.5) % 360) // 45)]


def quad_of(x: float, y: float) -> str:
    return QUAD_ORDER[0 if x >= 0 and y >= 0 else 1 if x >= 0 else 2 if y < 0 else 3]


def stretch(rel_rsi) -> str:
    lo, hi = cfg.ROTATION_RSI_CUTS
    if rel_rsi is None or pd.isna(rel_rsi):
        return ""
    return "Overbought" if rel_rsi >= hi else "Oversold" if rel_rsi <= lo else ""


def rotation_map(path: pd.DataFrame, now: pd.DataFrame) -> go.Figure:
    xlim = max(2.0, path["x"].abs().max() * 1.12)
    ylim = max(2.0, path["y"].abs().max() * 1.12)
    fig = go.Figure()
    for name, (x0, x1, y0, y1) in {"Leading": (0, xlim, 0, ylim), "Weakening": (0, xlim, -ylim, 0),
                                   "Lagging": (-xlim, 0, -ylim, 0), "Improving": (-xlim, 0, 0, ylim)}.items():
        fig.add_shape(type="rect", x0=x0, x1=x1, y0=y0, y1=y1, line={"width": 0}, layer="below",
                      fillcolor=_rgba(QUAD_COLORS[name], 0.10))
        fig.add_annotation(x=0.97 * (x1 if x1 > 0 else x0), y=0.95 * (y1 if y1 > 0 else y0), text=f"<b>{name}</b>",
                           showarrow=False, xanchor="right" if x1 > 0 else "left",
                           yanchor="top" if y1 > 0 else "bottom", font={"size": 14, "color": QUAD_COLORS[name]})
    for _, r in now.iterrows():
        p = path[path["ticker"] == r["ticker"]]
        n = len(p)
        color = QUAD_COLORS[r["quadrant"]]
        tag = {"Overbought": " ▲OB", "Oversold": " ▼OS"}.get(stretch(r["rel_rsi"]), "")
        fig.add_trace(go.Scatter(
            x=p["x"], y=p["y"], mode="lines+markers+text", name=f"{r['ticker']} · {r['name']}",
            line={"color": _rgba(color, 0.45), "width": 1.6, "shape": "spline", "smoothing": 0.6},
            marker={"color": color, "size": [5] * (n - 1) + [13],
                    "opacity": list(np.linspace(0.35, 0.8, n - 1)) + [1.0] if n > 1 else [1.0]},
            text=[""] * (n - 1) + [f"<b>{r['ticker']}</b>{tag}"], textposition="middle right",
            customdata=[[d.strftime("%b %d, %Y"), r["name"]] for d in p["date"]],
            hovertemplate=f"<b>{r['ticker']}</b> · %{{customdata[1]}}<br>%{{customdata[0]}}<br>"
                          "Trend %{x:.2f} · Momentum %{y:.2f}<extra></extra>",
        ))
    fig.update_layout(height=620, margin={"l": 0, "r": 0, "t": 10, "b": 0}, hovermode="closest",
                      legend={"font": {"size": 11}, "itemclick": "toggle", "itemdoubleclick": "toggleothers"})
    fig.update_xaxes(range=[-xlim, xlim], zeroline=True, zerolinewidth=1.5,
                     title=f"Relative trend: vs its {cfg.ROTATION_TREND_WEEKS}-week norm (σ) →")
    fig.update_yaxes(range=[-ylim, ylim], zeroline=True, zerolinewidth=1.5,
                     title=f"Relative momentum: {cfg.ROTATION_MOMENTUM_WEEKS}-week change in trend →")
    return fig


def _pct(v):
    return None if v is None else v * 100


def rotation_evidence(stats: dict, group: str) -> None:
    g = stats["groups"].get(group)
    if not g:
        st.info("No statistics for this group yet.")
        return
    h, split = stats["horizon_weeks"], pd.Timestamp(stats["split"])
    per = g["periods"]
    labels = {"before": f"before {split.year}", "after": f"{split.year} on"}
    spans = {k: (f"{per[k]['start'][:4]}–{per[k]['end'][:4]}" if per[k]["start"] else "no data") for k in per}
    st.markdown(f"**Which measures predicted the next {h} weeks?** Rank correlation across the {group.lower()} "
                f"between each reading and its return over the next {h} weeks, on non-overlapping periods.")
    rows = []
    for c in g["candidates"]:
        row = {"Measure": c["name"]}
        for k in ("before", "after"):
            row[f"IC {labels[k]}"] = c[k]["ic"]
            row[f"t {labels[k]}"] = c[k]["t"]
        rows.append(row)
    num = st.column_config.NumberColumn
    ui.table(pd.DataFrame(rows), hide_index=True, column_config={
        **{f"IC {labels[k]}": num(format="%+.3f", help=f"Mean rank correlation, {spans[k]}. "
                                  "0 = no information; ±0.05 is already decent for a cross-section.")
           for k in labels},
        **{f"t {labels[k]}": num(format="%+.1f", help="t-statistic of the mean; beyond ±2 is unlikely to be "
                                 "luck, if this were the only measure tested.") for k in labels},
    })
    st.markdown(f"**How each quadrant did over the next {h} weeks**, vs the group's average")
    qrows = []
    for q in QUAD_ORDER:
        row = {"Quadrant": q}
        for k in ("before", "after"):
            v = per[k]["quadrants"][q]
            row[f"Next {h} wks, {labels[k]}"] = _pct(v["mean"])
            row[f"Readings, {labels[k]}"] = v["n"]
        qrows.append(row)
    ui.table(pd.DataFrame(qrows), hide_index=True, column_config={
        f"Next {h} wks, {labels[k]}": num(format="%+.2f%%") for k in labels})
    lines = []
    lo, hi = stats["rsi_cuts"]
    for k in ("before", "after"):
        p = per[k]
        if not p["moves"]:
            continue
        m = p["moves"]
        line = (f"- **{labels[k].capitalize()}** ({spans[k]}): {h} weeks later an ETF had moved one quadrant "
                f"clockwise {m['clockwise']:.0%} of the time, counter-clockwise {m['counter']:.0%}, stayed "
                f"{m['stay']:.0%}, jumped across {m['opposite']:.0%}.")
        for side, word, cut in (("overbought", "fell back", f"≥ {hi}"), ("oversold", "bounced", f"≤ {lo}")):
            e = p[side]
            if e["n"]:
                line += (f" {side.capitalize()} (relative RSI {cut}): next {h} weeks {e['mean'] * 100:+.2f}% vs "
                         f"the group, {word} {e['reversed']:.0%} of {e['n']} times.")
        lines.append(line)
    if lines:
        st.markdown("\n".join(lines))
    st.caption("Clockwise motion is partly built in: momentum is the change in trend, so any swing in "
               "relative strength traces a clockwise loop. The map shows where each ETF is in its cycle, not how "
               "far it will go. Several measures were tested, so one good-looking t-statistic can be luck; a "
               "result that holds in both periods is the one to trust.")


st.markdown("##### Rotation map")
rot_path, rot_now, rot_stats = load("rotation_path"), load("rotation_now"), load("rotation_stats", "json")
with st.container(border=True):
    if rot_now is None or rot_now.empty or rot_path is None:
        st.info("No rotation data yet. Run `python run_jobs.py`.")
    else:
        groups = [g for g in cfg.ROTATION_GROUPS if (rot_now["group"] == g).any()]
        c1, c2 = st.columns([1.4, 1], vertical_alignment="center")
        with c1:
            rgroup = ui.choice("Group", groups, key="rot_group")
        with c2:
            tail = int(ui.choice("Tail", ["4 wk", "8 wk", "13 wk", "26 wk"], key="rot_tail").split()[0])
        now = rot_now[rot_now["group"] == rgroup].sort_values("angle")
        path = rot_path[rot_path["group"] == rgroup].sort_values("date")
        path = path.groupby("ticker", group_keys=False).tail(tail + 1)
        ui.chart(rotation_map(path, now), key="rotation_map")

        # quadrant changes over the last momentum window, and stretched readings
        m = cfg.ROTATION_MOMENTUM_WEEKS
        moved = {}  # destination quadrant -> tickers that entered it
        for _, r in now.iterrows():
            p = rot_path[(rot_path["group"] == rgroup) & (rot_path["ticker"] == r["ticker"])].sort_values("date")
            if len(p) > m and quad_of(p["x"].iloc[-1 - m], p["y"].iloc[-1 - m]) != r["quadrant"]:
                moved.setdefault(r["quadrant"], []).append(r["ticker"])
        a, b, c = st.columns(3)
        a.markdown(f"**Entered a quadrant ({m} wks)**  \n"
                   + ("  \n".join(f"→ {q}: {', '.join(moved[q])}" for q in QUAD_ORDER if q in moved) or "none"))
        b.markdown("**Overbought vs SPY**  \n" + (", ".join(now.loc[now["rel_rsi"] >= cfg.ROTATION_RSI_CUTS[1],
                                                                  "ticker"]) or "none"))
        c.markdown("**Oversold vs SPY**  \n" + (", ".join(now.loc[now["rel_rsi"] <= cfg.ROTATION_RSI_CUTS[0],
                                                                "ticker"]) or "none"))

        table = pd.DataFrame({
            "ETF": now["ticker"], "Name": now["name"], "Quadrant": now["quadrant"],
            "Heading": [heading(dx, dy) for dx, dy in zip(now["dx"], now["dy"])],
            "Trend": now["x"], "Momentum": now["y"], "Rel. RSI": now["rel_rsi"],
            "Stretch": [stretch(v) for v in now["rel_rsi"]], f"{m}-wk vs SPY": now["rel_ret"], "RSI": now["rsi"],
        })
        num = st.column_config.NumberColumn
        ui.table(table, hide_index=True, height=35 * (len(table) + 1) + 3, column_config={
            "Heading": st.column_config.TextColumn(help=f"Direction of travel on the map over the last {m} weeks"),
            "Trend": num(format="%+.2f", help="Across: relative strength vs SPY compared with its own "
                                              f"{cfg.ROTATION_TREND_WEEKS}-week norm, in standard deviations"),
            "Momentum": num(format="%+.2f", help=f"Up: change in trend over the last {m} weeks"),
            "Rel. RSI": st.column_config.ProgressColumn(
                format="%.0f", min_value=0, max_value=100, color=ui.PALETTE["grey"],
                help=f"{cfg.ROTATION_RSI_WEEKS}-week RSI of the ETF / SPY ratio. "
                     f"≥ {cfg.ROTATION_RSI_CUTS[1]} overbought, ≤ {cfg.ROTATION_RSI_CUTS[0]} oversold vs SPY"),
            f"{m}-wk vs SPY": num(format="%+.1f%%"),
            "RSI": num(format="%.0f", help="The ETF's own 14-day RSI (absolute, not relative to SPY)"),
        })
        st.caption(f"Weekly closes through {path['date'].max():%b %d, %Y}, relative to SPY. Sorted clockwise "
                   "from the top of Leading. Strength tends to cycle Improving → Leading → Weakening → Lagging. "
                   "▲OB / ▼OS on the map = overbought / oversold vs SPY. Click legend entries to hide ETFs.")
        if rot_stats:
            with st.expander("Does the map predict anything? Tested on the full history"):
                rotation_evidence(rot_stats, rgroup)

# ================================================================= sector internals
SECTOR_NAMES = dict(cfg.SECTORS)


def participation_check(momentum, beating) -> str:
    """Does participation inside the sector agree with where the map says it's heading?"""
    if momentum is None or beating is None or pd.isna(momentum) or pd.isna(beating):
        return ""
    broad = beating >= cfg.INTERNALS_BROAD if momentum > 0 else beating < cfg.INTERNALS_BROAD
    return "Confirms" if broad else "Narrow"


def contrib_chart(c: pd.DataFrame, n: int = 8) -> go.Figure:
    c = c.sort_values("contrib")
    show = pd.concat([c.head(n), c.tail(n)]).drop_duplicates("ticker") if len(c) > 2 * n else c
    fig = go.Figure(go.Bar(
        x=show["contrib"], y=show["ticker"], orientation="h",
        marker_color=[ui.PALETTE["teal"] if v >= 0 else ui.PALETTE["red"] for v in show["contrib"]],
        customdata=show[["name", "weight", "ret", "rel"]].to_numpy(),
        hovertemplate="<b>%{y}</b> · %{customdata[0]}<br>Contribution %{x:+.2f} pts<br>"
                      "Weight %{customdata[1]:.1f}% · return %{customdata[2]:+.1f}% "
                      "(%{customdata[3]:+.1f} vs SPY)<extra></extra>",
    ))
    fig.update_layout(height=max(260, 22 * len(show) + 40), margin={"l": 0, "r": 0, "t": 10, "b": 0},
                      xaxis={"title": "Contribution to the sector's move vs SPY (% points)", "zeroline": True},
                      yaxis={"automargin": True})
    return fig


def confirmation_evidence(s: dict) -> None:
    h = s["horizon_weeks"]
    st.markdown(f"Each week from {s['start'][:7]} to {s['end'][:7]}, every sector was sorted by the rotation map's "
                f"momentum (rising or falling) and by participation ({s['broad']}% of members beating SPY over "
                f"{s['window_days']} days). How did it do over the next {h} weeks against the other sectors?")
    labels = {"rising_broad": ("Rising", "Broad (confirms)"), "rising_narrow": ("Rising", "Narrow"),
              "falling_broad": ("Falling", "Broad (confirms)"), "falling_narrow": ("Falling", "Narrow")}
    rows = [{"Momentum": a, "Participation": b, f"Next {h} wks vs sectors": _pct(s[k]["mean"]),
             "Beat the sectors": _pct(s[k]["hit"]), "Readings": s[k]["n"]} for k, (a, b) in labels.items()]
    num = st.column_config.NumberColumn
    ui.table(pd.DataFrame(rows), hide_index=True, column_config={
        f"Next {h} wks vs sectors": num(format="%+.2f%%"),
        "Beat the sectors": num(format="%.0f%%")})
    ic = s["ic_beating"]
    if ic["ic"] is not None:
        st.markdown(f"Ranking sectors by participation alone: rank correlation with the next {h} weeks "
                    f"{ic['ic']:+.3f} (t {ic['t']:+.1f}, {ic['n']} periods).")
    st.caption("If participation confirmed rotations, rising + broad would beat rising + narrow, and falling + broad "
               "would trail falling + narrow. Caveats: only five years of member prices; today's S&P 500 members "
               "(companies that left the index are missing); weights are approximated from today's market caps.")


st.markdown("##### Sector internals")
internals, contrib, confirm = load("sector_internals"), load("sector_contrib"), load("sector_confirmation", "json")
with st.container(border=True):
    if internals is None or internals.empty or contrib is None:
        st.info("No sector internals yet. Run `python run_jobs.py`.")
    else:
        last = internals[internals["date"] == internals["date"].max()].set_index("sector")
        sec_now = (rot_now[rot_now["group"] == "Sectors"].set_index("ticker")
                   if rot_now is not None and not rot_now.empty else pd.DataFrame())
        order = [t for t in (sec_now.sort_values("angle").index if len(sec_now) else last.index) if t in last.index]
        table = pd.DataFrame({
            "Sector": order, "Name": [SECTOR_NAMES.get(t, t) for t in order],
            "Quadrant": [sec_now["quadrant"].get(t, "") if len(sec_now) else "" for t in order],
            "Beating SPY": last.loc[order, "beating"].to_numpy(),
            "Above 50-day": last.loc[order, "above_50"].to_numpy(),
            "Above 200-day": last.loc[order, "above_200"].to_numpy(),
            "Net new highs": last.loc[order, "net_highs"].to_numpy(),
            "EW − CW": last.loc[order, "ew_cw"].to_numpy(),
            "Check": [participation_check(sec_now["y"].get(t) if len(sec_now) else None, last.at[t, "beating"])
                      for t in order],
        })
        num, prog = st.column_config.NumberColumn, st.column_config.ProgressColumn
        w = cfg.INTERNALS_WINDOW
        ui.table(table, hide_index=True, height=35 * (len(table) + 1) + 3, column_config={
            "Beating SPY": prog(format="%.0f%%", min_value=0, max_value=100, color=ui.PALETTE["grey"],
                                help=f"Share of the sector's S&P 500 members that beat SPY over {w} trading days"),
            "Above 50-day": num(format="%.0f%%"), "Above 200-day": num(format="%.0f%%"),
            "Net new highs": num(format="%+.0f%%", help=f"Members that made a new 52-week high in the last {w} days "
                                                          "minus those that made a new low, as % of members"),
            "EW − CW": num(format="%+.1f", help=f"Equal-weighted minus cap-weighted {w}-day return, % points. "
                                                "Positive = the average member did better than the giants."),
            "Check": st.column_config.TextColumn(
                help=f"Confirms: rising momentum with ≥ {cfg.INTERNALS_BROAD}% of members beating SPY, or falling "
                     f"momentum with fewer. Narrow: the move rests on a few names."),
        })

        st.markdown("**What's driving it**")
        c1, c2 = st.columns([1.4, 1], vertical_alignment="center")
        with c1:
            pick = st.selectbox("Sector", order, format_func=lambda t: f"{t} · {SECTOR_NAMES.get(t, t)}",
                                key="internals_sector", label_visibility="collapsed")
        with c2:
            win = ui.choice("Window", list(cfg.CONTRIBUTION_WINDOWS), key="internals_window", default="4 wk")
        c = contrib[(contrib["sector"] == pick) & (contrib["window"] == win)]
        if c.empty:
            st.info("No member data for this sector.")
        else:
            total = c["contrib"].sum()
            lead = c.sort_values("contrib", ascending=total < 0).head(3)
            m1, m2, m3 = st.columns(3)
            m1.metric(f"{pick} members vs SPY, cap-weighted", f"{total:+.2f} pts")
            m2.metric("From the top 3 names", f"{lead['contrib'].sum():+.2f} pts", ", ".join(lead["ticker"]),
                      delta_color="off", delta_arrow="off")
            m3.metric("Members beating SPY", f"{(c['rel'] > 0).mean():.0%}", f"{len(c)} members", delta_color="off",
                      delta_arrow="off")
            left, right = st.columns([1.3, 1])
            with left:
                ui.chart(contrib_chart(c), key="contrib_chart")
            with right:
                hist = internals[internals["sector"] == pick]
                fig = go.Figure(go.Scatter(x=hist["date"], y=hist["beating"], mode="lines", line={"width": 1.6},
                                           hovertemplate="%{x|%b %d}: %{y:.0f}%<extra></extra>"))
                fig.add_hline(y=cfg.INTERNALS_BROAD, line_dash="dot", line_color=ui.PALETTE["grey"])
                fig.update_layout(height=260, margin={"l": 0, "r": 0, "t": 26, "b": 0}, yaxis={"range": [0, 100]},
                                  title={"text": f"{pick} members beating SPY over {w} days, 1 year",
                                         "font": {"size": 13}})
                ui.chart(fig, key="participation_hist")
            st.caption(f"Contribution = weight at the start × (return − SPY's return); they add up to the members' "
                       f"cap-weighted move vs SPY. Weights come from today's market caps, so they approximate "
                       f"{pick}'s actual holdings. As of {internals['date'].max():%b %d, %Y}.")
        if confirm:
            with st.expander("Does participation confirm a rotation? Tested on five years"):
                confirmation_evidence(confirm)

# ================================================================= fund flows
def flows_evidence(stats: dict) -> None:
    h, split = stats["horizon_weeks"], pd.Timestamp(stats["split"]).year
    st.markdown(f"Each week, sectors were ranked by their fund flows as a share of assets (as known the day "
                f"before). Did that rank line up with the next {h} weeks' return vs the other sectors?")
    rows = []
    for label, per in stats["signals"].items():
        for key, name in (("before", f"before {split}"), ("after", f"{split} on")):
            ic, sp = per[key]["ic"], per[key]["spread"]
            rows.append({"Flows over": label, "Period": name, "Rank correlation": ic["ic"], "t": ic["t"],
                         f"Top 2 − bottom 2, next {h} wks": _pct(sp["mean"]), "Periods": ic["n"]})
    num = st.column_config.NumberColumn
    ui.table(pd.DataFrame(rows), hide_index=True, column_config={
        "Rank correlation": num(format="%+.3f"), "t": num(format="%+.1f"),
        f"Top 2 − bottom 2, next {h} wks": num(format="%+.2f%%", help="Average return of the two sectors with "
                                                                      "the biggest inflows minus the two with the "
                                                                      "biggest outflows, vs the sectors' average")})
    st.caption("Positive = money chasing a sector kept being right (momentum); negative = crowds arrived late "
               "(contrarian). Near zero in either period = flows confirm nothing on their own.")


st.markdown("##### Fund flows")
flows_sum, flows_hist = load("flows_summary", "json"), load("flows_history")
with st.container(border=True):
    if not flows_sum or not flows_sum.get("rows") or flows_hist is None:
        st.info("No fund-flow data yet. Run `python run_jobs.py`.")
    else:
        fr = pd.DataFrame(flows_sum["rows"]).sort_values("pct_4 wk", ascending=False)
        fr["name"] = fr["ticker"].map(SECTOR_NAMES)
        left, right = st.columns([1, 1.25])
        with left:
            fig = go.Figure(go.Bar(
                x=fr["pct_4 wk"], y=fr["ticker"], orientation="h",
                marker_color=[ui.PALETTE["teal"] if v >= 0 else ui.PALETTE["red"] for v in fr["pct_4 wk"]],
                customdata=np.c_[fr["name"], fr["usd_4 wk"] / 1e9],
                hovertemplate="<b>%{y}</b> · %{customdata[0]}<br>%{x:+.1f}% of assets<br>"
                              "$%{customdata[1]:+.2f}bn<extra></extra>"))
            fig.update_layout(height=330, margin={"l": 0, "r": 0, "t": 26, "b": 0},
                              yaxis={"autorange": "reversed"},
                              title={"text": "Net flows over 4 weeks, % of fund assets", "font": {"size": 13}})
            ui.chart(fig, key="flows_bar")
        with right:
            table = pd.DataFrame({
                "Fund": fr["ticker"],
                **{f"{label} ($bn)": fr[f"usd_{label}"] / 1e9 for label in ("1 wk", "4 wk")},
                "4 wk % assets": fr["pct_4 wk"], "13 wk % assets": fr["pct_13 wk"],
                "vs history": fr["pct_rank_4wk"],
            })
            num = st.column_config.NumberColumn
            ui.table(table, hide_index=True, height=35 * (len(table) + 1) + 3, column_config={
                **{f"{label} ($bn)": num(format="%+.2f") for label in ("1 wk", "4 wk")},
                "4 wk % assets": num(format="%+.1f%%"), "13 wk % assets": num(format="%+.1f%%"),
                "vs history": num(format="%.0f", help="Percentile of the 4-week flow (% of assets) within the "
                                                      "fund's own history: 95 = bigger inflows than 95% of days"),
            })
        st.caption(f"Flows = daily change in shares outstanding × NAV, from State Street's NAV-history files "
                   f"for the Select Sector SPDRs (since 2003). Share splits, launches and XLRE's 2016 spin-off "
                   f"are excluded. Through {fr['date'].max()}. Money moving in alongside a rotation is "
                   "confirmation; a rotation without it, or against it, is less convincing.")
        if flows_sum.get("stats"):
            with st.expander("Have flows predicted anything? Tested since 2004"):
                flows_evidence(flows_sum["stats"])

# ================================================================= estimate revisions


st.markdown("##### Estimate revisions & analyst actions")
rev, rev_names, rev_hist, rev_sum = (load_other("revisions", "sector_revisions"),
                                     load_other("revisions", "revisions_names"),
                                     load_other("revisions", "revisions_history"),
                                     load_other("revisions", "summary", "json"))
with st.container(border=True):
    if rev is None or rev.empty or not rev_sum:
        st.info("No revision data. It comes from the TickerLake project (its daily `analyst` stage, published "
                "by the `revisions` job); see the README.")
    else:
        rev = rev.assign(etf=rev["gics_sector"].map(cfg.GICS_TO_ETF)).sort_values("rev_30d", ascending=False)
        days = rev_sum["action_days"]
        table = pd.DataFrame({
            "Sector": rev["etf"], "Name": rev["gics_sector"], "Names": rev["names"],
            "EPS rev. 30d": rev["rev_30d"], "EPS rev. 90d": rev["rev_90d"],
            "Rising estimates": rev["rising_share"], "Revision balance": rev["breadth"],
            **({f"Up/down-grades {days}d": [f"{int(u)} / {int(d)}" for u, d in zip(rev["upgrades"],
                                                                                    rev["downgrades"])],
                f"Targets raised/cut {days}d": [f"{int(u)} / {int(d)}" for u, d in zip(rev["targets_raised"],
                                                                                        rev["targets_cut"])]}
               if "upgrades" in rev else {}),
        })
        num = st.column_config.NumberColumn
        ui.table(table, hide_index=True, height=35 * (len(table) + 1) + 3, column_config={
            "EPS rev. 30d": num(format="%+.2f%%", help="Median change in next fiscal year's EPS estimate over "
                                                     "30 days, across the sector's members"),
            "EPS rev. 90d": num(format="%+.2f%%"),
            "Rising estimates": num(format="%.0f%%", help="Share of members whose estimate rose over 30 days"),
            "Revision balance": num(format="%+.0f", help="Analyst revisions over 30 days (this and next fiscal "
                                                         "year): (up − down) / (up + down) × 100"),
        })
        if rev_names is not None and not rev_names.empty:
            pick = st.selectbox("Sector", list(rev["gics_sector"]), key="rev_sector", label_visibility="collapsed",
                                format_func=lambda g: f"{cfg.GICS_TO_ETF.get(g, '')} · {g}")
            n = rev_names[rev_names["gics_sector"] == pick].dropna(subset=["rev_30d"]).sort_values("rev_30d")
            show = pd.concat([n.tail(5).iloc[::-1], n.head(5)]).drop_duplicates("symbol")
            ui.table(pd.DataFrame({"Company": show["symbol"] + " · " + show["name"].fillna(""),
                                   "EPS rev. 30d": show["rev_30d"], "EPS rev. 90d": show["rev_90d"],
                                   "Analysts up / down (30d)": [f"{int(u)} / {int(d)}" for u, d in
                                                                zip(show["up_30d"].fillna(0),
                                                                    show["down_30d"].fillna(0))]}),
                     hide_index=True, column_config={"EPS rev. 30d": num(format="%+.1f%%"),
                                                     "EPS rev. 90d": num(format="%+.1f%%")})
        if rev_hist is not None and rev_hist["snapshot_date"].nunique() >= 5:
            fig = go.Figure()
            for g, s in rev_hist.sort_values("snapshot_date").groupby("gics_sector"):
                fig.add_trace(go.Scatter(x=s["snapshot_date"], y=s["breadth"], mode="lines",
                                         name=cfg.GICS_TO_ETF.get(g, g), line={"width": 1.4}))
            fig.update_layout(height=280, margin={"l": 0, "r": 0, "t": 26, "b": 0},
                              title={"text": "Revision balance by sector", "font": {"size": 13}})
            ui.chart(fig, key="revision_history")
        st.caption(f"Yahoo consensus via TickerLake, snapshot {rev_sum['snapshot_date']}: {rev_sum['covered']} of "
                   f"{rev_sum['members']} members. Yahoo keeps no estimate history, so the daily snapshots "
                   f"(since {rev_sum['first_snapshot']}, {rev_sum['snapshots']} so far) are what will let these "
                   "readings be tested; a history chart appears after five. Rating actions on single stocks were "
                   "tested on 2012-2026 history (TickerLake `scripts/backtest_analyst_ratings.py`): the price moves "
                   "at the announcement, and what follows is too small to beat trading costs.")

# ================================================================= leadership
st.markdown("##### Sector leadership")
lead_df, disp = load("sector_leadership"), load("sector_dispersion")
with st.container(border=True):
    if lead_df is None or lead_df.empty:
        st.info("No leadership data yet. Run `python run_jobs.py`.")
    else:
        latest = lead_df.iloc[-1].sort_values(ascending=False)
        z = lead_df[latest.index].T
        ranks = lead_df[latest.index].rank(axis=1, ascending=False).T
        lim = float(np.nanpercentile(np.abs(z.to_numpy()), 95)) or 1.0
        fig = go.Figure(go.Heatmap(
            z=z.to_numpy(), x=z.columns, y=[f"{t} {SECTOR_NAMES.get(t, '')}" for t in z.index],
            zmin=-lim, zmax=lim, zmid=0, customdata=ranks.to_numpy(),
            colorscale=[(0, ui.PALETTE["red"]), (0.5, "#5C6670"), (1, ui.PALETTE["teal"])],
            colorbar={"title": "% vs SPY", "thickness": 10}, xgap=1, ygap=1,
            hovertemplate="<b>%{y}</b><br>4 weeks to %{x|%b %d, %Y}: %{z:+.1f}% vs SPY<br>"
                          "Rank %{customdata:.0f} of " + str(len(z)) + "<extra></extra>",
        ))
        fig.update_layout(height=40 + 26 * len(z), margin={"l": 0, "r": 0, "t": 10, "b": 0},
                          yaxis={"autorange": "reversed"})
        ui.chart(fig, key="leadership")
        st.caption(f"Each cell: the sector's {cfg.ROTATION_MOMENTUM_WEEKS}-week return minus SPY's, week by week. "
                   "Sorted by the latest week. Long runs of one colour = persistent leadership; colour flips across "
                   "many rows at once = a rotation.")
        if disp is not None and not disp.empty:
            recent = disp[disp.index >= disp.index[-1] - pd.DateOffset(years=5)]
            a, b = st.columns(2)
            for col, key, title, fmt in ((a, "dispersion", "Dispersion: spread of 4-week sector returns", "%{y:.1f} pts"),
                                         (b, "correlation", f"Average correlation between sectors, "
                                                            f"{cfg.DISPERSION_DAYS} days", "%{y:.2f}")):
                s = disp[key].dropna()
                if s.empty:
                    continue
                pct = (s < s.iloc[-1]).mean() * 100
                fig = go.Figure(go.Scatter(x=recent.index, y=recent[key], mode="lines", line={"width": 1.6},
                                           hovertemplate="%{x|%b %d, %Y}: " + fmt + "<extra></extra>"))
                fig.update_layout(height=210, margin={"l": 0, "r": 0, "t": 26, "b": 0},
                                  title={"text": title, "font": {"size": 13}})
                with col:
                    ui.chart(fig, key=f"disp_{key}")
                    st.caption(f"Now {s.iloc[-1]:.2f}: higher than {pct:.0f}% of weeks since {s.index[0]:%Y}.")
            st.caption("Dispersion is how far apart the sectors' 4-week returns are; correlation, how much they move "
                       "together. Neither one forecasts a change in leadership. Tested on the nine original sector SPDRs "
                       "since 2000 (340 non-overlapping 4-week periods, measured 2026-11-13): high dispersion and low "
                       "correlation left the link between last month's and next month's relative returns unchanged "
                       "(t 0.3 each). Last month's leaders trail slightly the next month whatever the dispersion "
                       "(rank correlation -0.04). One thing correlation does foreshadow: unusually high correlation "
                       "came before wider sector moves the next month (t -3.0), i.e. stress, not direction.")

# ================================================================= cross-asset
st.markdown("##### Cross-asset checks")
xa, xa_hist = load("cross_asset", "json"), load("cross_asset_history")
with st.container(border=True):
    if not xa or xa_hist is None:
        st.info("No cross-asset data yet. Run `python run_jobs.py`.")
    else:
        wks, cw = xa["weeks"], xa["corr_weeks"]

        def _chg(p):
            return f"{p['driver_change']:+.1f}%" if p["kind"] == "yahoo" else f"{p['driver_change']:+.2f} pts"

        table = pd.DataFrame([{
            "Sector": p["name"], "Driver": p["driver"],
            "Expected": "moves with it" if p["sign"] > 0 else "moves against it",
            f"Sector, {wks} wks": p["rel_change"], f"Driver, {wks} wks": _chg(p),
            "Agrees": "Yes" if p["agrees"] else "No" if p["agrees"] is not None else "",
            f"Link, last {cw} wks": p["corr_recent"], "Link, full history": p["corr_all"],
        } for p in xa["pairs"]])
        num = st.column_config.NumberColumn
        ui.table(table, hide_index=True, column_config={
            f"Sector, {wks} wks": num(format="%+.1f%%", help="Relative return vs SPY (offense/defense: cyclicals "
                                                             "minus defensives)"),
            f"Link, last {cw} wks": num(format="%+.2f", help="Correlation of weekly changes, signed so that "
                                                            "positive = moving the expected way"),
            "Link, full history": num(format="%+.2f", help="The same, since both series exist (1999-2000 for most, "
                                                          "2015 for XLRE)"),
        })
        names = {p["pair"]: f"{p['name']} · {p['driver']}" for p in xa["pairs"]}
        pick = st.selectbox("Pair", list(names), format_func=names.get, key="xa_pair", label_visibility="collapsed")
        h = xa_hist[xa_hist["pair"] == pick]
        p = next(p for p in xa["pairs"] if p["pair"] == pick)
        st.caption(f"Why: {p['why']}. Link since {p['since'][:4]}: {p['corr_all']:+.2f}; "
                   f"last {cw} weeks: {p['corr_recent']:+.2f}.")
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
                            subplot_titles=(f"{p['name']}, % since {h['date'].iloc[0]:%b %Y}", p["driver"]))
        fig.add_trace(go.Scatter(x=h["date"], y=h["rel"], mode="lines", line={"width": 1.6}, name=p["name"],
                                 hovertemplate="%{x|%b %d, %Y}: %{y:+.1f}%<extra></extra>"), row=1, col=1)
        fig.add_trace(go.Scatter(x=h["date"], y=h["driver"], mode="lines", line={"width": 1.6, "color":
                                 ui.PALETTE["grey"]}, name=p["driver"],
                                 hovertemplate="%{x|%b %d, %Y}: %{y:.2f}<extra></extra>"), row=2, col=1)
        fig.update_layout(height=420, margin={"l": 0, "r": 0, "t": 30, "b": 0}, showlegend=False)
        ui.chart(fig, key="cross_asset_chart")
        st.caption("A rotation is more believable when the driver behind it agrees, but check the link columns "
                   "first: a textbook relationship that has been near zero for a year isn't confirming anything.")

# ================================================================= global markets
st.subheader("Global markets")
gm = load("global_markets")
if gm is None or gm.empty:
    st.info("No global market data yet. Rerun the market job.")
else:
    groups = [g for g in dict.fromkeys(gm["group"])]
    c1, c3 = st.columns(2)
    with c1:
        group = ui.choice("Markets", groups, key="gm_group")
    with c3:
        period = ui.choice("Period", ["1D", "1W", "MTD", "YTD", "1Y"], key="gm_period", default="YTD")
    sub = gm[gm["group"] == group]
    regions = list(dict.fromkeys(sub["region"]))
    picked = st.multiselect("Region", regions, default=[], key=f"gm_region_{group}", placeholder="All regions",
                            label_visibility="collapsed")
    if picked:
        sub = sub[sub["region"].isin(picked)]
    bars = sub.dropna(subset=[period]).sort_values(period)
    fig = go.Figure(go.Bar(
        x=bars[period], y=bars["name"], orientation="h",
        marker_color=[ui.PALETTE["teal"] if v >= 0 else ui.PALETTE["red"] for v in bars[period]],
        customdata=bars["ticker"], hovertemplate="%{y} (%{customdata}): %{x:+.2f}%<extra></extra>"))
    fig.add_vline(x=0, line_width=1, line_color=ui.PALETTE["grey"])
    fig.update_layout(height=max(220, 24 * len(bars) + 40), margin={"l": 0, "r": 0, "t": 10, "b": 0},
                      xaxis={"ticksuffix": "%"}, bargap=0.25)
    ui.chart(fig, key="gm_bars")

    view = pd.DataFrame({
        "Market": sub["name"] + " (" + sub["ticker"] + ")",
        "1D": sub["1D"], "MTD": sub["MTD"], "YTD": sub["YTD"], "1Y": sub["1Y"],
        "52-wk range": sub["range_pos"], "vs 200-day": sub["vs_200d"],
        "200d": sub["sma200_rising"].map({True: "↑", False: "↓"}),
        "RSI 14": sub["rsi14"], "Last year": sub["spark"].map(lambda x: list(x) if x is not None else [])})
    pct = ["1D", "MTD", "YTD", "1Y", "vs 200-day"]
    styled = view.style.map(lambda v: f"color: {ui.PALETTE['teal']}" if pd.notna(v) and v > 0
                            else (f"color: {ui.PALETTE['red']}" if pd.notna(v) and v < 0 else ""), subset=pct)
    num = st.column_config.NumberColumn
    ui.table(styled, hide_index=True, height=35 * (len(view) + 1) + 3, column_config={
        "Market": st.column_config.TextColumn(width="medium"),
        **{c: num(format="%+.1f%%", width="small") for c in pct}, "1D": num(format="%+.2f%%", width="small"),
        "52-wk range": st.column_config.ProgressColumn(
            min_value=0, max_value=100, format="%.0f", width="small",
            help="Where the last close sits between the 52-week low (0) and high (100)"),
        "200d": st.column_config.TextColumn(width="small", help="200-day average higher (↑) or lower (↓) than 20 sessions ago"),
        "RSI 14": num(format="%.0f", width="small", help="14-day relative strength index: above 70 stretched up, below 30 down"),
        "Last year": st.column_config.LineChartColumn(width="small", help="Weekly closes over the last year")})
    st.caption(f"US-listed ETFs, total return (Yahoo's dividend-adjusted closes) through {pd.Timestamp(gm['date'].max()):%b %d, %Y}. "
               "Descriptive: trend and RSI readings like these were tested on sector ETFs (Rotation section) and "
               "didn't predict which would do better next.")

# ================================================================= treemap
st.subheader("Market map")
cons = load("constituents_perf")
with st.container(border=True):
    if cons is None or cons.empty:
        st.info("No stock data.")
    else:
        c1, c2 = st.columns([1, 2.2], vertical_alignment="center")
        scopes = ["S&P 500"] + (["Nasdaq 100"] if cons["ndx"].any() else [])
        with c1:
            scope = ui.choice("Index", scopes, key="tm_scope")
        with c2:
            tm_tf = ui.choice("Timeframe", cfg.TIMEFRAMES, key="tm_tf")
        df = cons[cons["sp500"] if scope == "S&P 500" else cons["ndx"]].copy()
        df["market_cap"] = df["market_cap"].fillna(df["market_cap"].median())
        df = df.dropna(subset=[tm_tf, "market_cap"])
        lim = max(cfg.FLAT_BAND[tm_tf] * 10, 1.0)
        # Build the tree explicitly: sector and index boxes show the cap-weighted return.
        ids, labels, parents, values, colors, names = [], [], [], [], [], []
        w = df["market_cap"]
        root_ret = float((df[tm_tf] * w).sum() / w.sum()) if len(df) else 0.0
        ids.append("root"); labels.append(scope); parents.append(""); values.append(float(w.sum()))
        colors.append(root_ret); names.append(scope)
        for sector, g in df.groupby("sector"):
            sid = f"sector:{sector}"
            ids.append(sid); labels.append(sector); parents.append("root")
            values.append(float(g["market_cap"].sum()))
            colors.append(float((g[tm_tf] * g["market_cap"]).sum() / g["market_cap"].sum()))
            names.append(sector)
            for _, r in g.iterrows():
                ids.append(f"{sid}/{r['symbol']}"); labels.append(r["symbol"]); parents.append(sid)
                values.append(float(r["market_cap"])); colors.append(float(r[tm_tf])); names.append(str(r["name"]))
        fig = go.Figure(go.Treemap(
            ids=ids, labels=labels, parents=parents, values=values, branchvalues="total",
            customdata=list(zip(names, colors)),
            marker={"colors": colors, "cmin": -lim, "cmax": lim, "cmid": 0, "line": {"width": 0.5},
                    "colorscale": [(0, ui.PALETTE["red"]), (0.5, ui.PALETTE["amber"]), (1, ui.PALETTE["teal"])],
                    "showscale": True, "colorbar": {"title": "%", "thickness": 10}},
            texttemplate="<b>%{label}</b><br>%{customdata[1]:+.2f}%", textposition="middle center",
            hovertemplate="<b>%{label}</b> · %{customdata[0]}<br>%{customdata[1]:+.2f}%<extra></extra>",
        ))
        fig.update_layout(height=640, margin={"l": 0, "r": 0, "t": 4, "b": 0})
        ui.chart(fig, key="treemap")
        st.caption(f"{len(df)} stocks · box size = market cap · color = {tm_tf} % change · click a sector to zoom in")

# ================================================================= method
with st.expander("Data sources & method"):
    st.markdown(
        "- **Prices:** Yahoo Finance (via `yfinance`), adjusted daily closes. Index members from Wikipedia.\n"
        "- **Macro:** FRED (St. Louis Fed) public CSVs: credit spreads, Treasury yields, Fed balance sheet, "
        "Treasury General Account, reverse repo, bank reserves, broad dollar, NFCI, leading indicators, real GDP.\n"
        "- **Fear / Greed & Technical:** each component is ranked against its own trailing two years "
        "(0 = lowest, 100 = highest) and averaged. RSI and stochastic are used as-is.\n"
        "- **Liquidity:** each factor is z-scored against its trailing ~3 years, signed so that higher means "
        "looser, capped at ±2.5 standard deviations and scaled to ±100.\n"
        "- **Economic:** each indicator's 6-month change is z-scored over 20 years and weighted by its historical "
        "correlation with real GDP growth 6 months later.\n"
        "- **Breadth** uses S&P 500 members as a proxy for the full NYSE.\n"
        "- **Trend** compares each reading with the one 1 week and 1 month earlier (economic: 1 and 3 months).\n"
        "- **Gauges vs the S&P 500:** *moves with the market* correlates each gauge's change with SPY's return "
        "over the same month; *next-period link* rank-correlates the reading with SPY's return over the next "
        "month (3 months for economic), using each reading only after its inputs were published. Both use "
        "non-overlapping periods. The technical gauge and these statistics use SPY's full history since 1993.\n\n"
        "All recipes, tickers and series live in `modules/market/config.py`."
    )
