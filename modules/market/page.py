"""Market Environment page. Reads only from the hub data folder."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import store, ui
from modules.market import config as cfg

MODULE = cfg.MODULE


@st.cache_data(show_spinner=False)
def _cached(name: str, kind: str, stamp):
    return store.load_json(MODULE, name) if kind == "json" else store.load_frame(MODULE, name)


def load(name: str, kind: str = "frame"):
    return _cached(name, kind, store.stamp(MODULE, name))


def _fmt(v, digits=2):
    return "—" if v is None or pd.isna(v) else f"{v:,.{digits}f}"


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

        with st.expander("History"):
            if key == "economic":
                h = econ_history["economic"].dropna() if econ_history is not None else pd.Series(dtype=float)
                h = h[h.index >= h.index.max() - pd.DateOffset(years=10)] if len(h) else h
            else:
                h = history[key].dropna() if history is not None and key in history else pd.Series(dtype=float)
                h = h[h.index >= h.index.max() - pd.DateOffset(years=2)] if len(h) else h
            if len(h):
                fig = go.Figure(go.Scatter(x=h.index, y=h.values, mode="lines", line={"width": 1.6},
                                           hovertemplate="%{x|%b %d, %Y}: %{y:.1f}<extra></extra>"))
                for c in g["cuts"]:
                    fig.add_hline(y=c, line_dash="dot", line_width=1, opacity=0.5)
                fig.update_layout(height=200, margin={"l": 0, "r": 0, "t": 4, "b": 0},
                                  yaxis={"range": [g["lo"], g["hi"]]}, showlegend=False)
                ui.chart(fig, key=f"hist_{key}")

# ================================================================= breadth & style
st.subheader("Breadth & style")
left, right = st.columns([1, 1.2])
breadth = load("breadth")

with left, st.container(border=True):
    st.markdown("**Market breadth** · S&P 500 members")
    if breadth is None or breadth.empty:
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
        st.caption(f"As of {breadth.index[-1]:%b %d, %Y}")

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
        "- **Breadth** uses S&P 500 members as a proxy for the full NYSE.\n\n"
        "All recipes, tickers and series live in `modules/market/config.py`."
    )
