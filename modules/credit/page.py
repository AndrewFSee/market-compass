"""Credit page. Reads only what credit-spread-analyzer publishes into the hub data folder."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from core import apps, store, ui
from modules.credit import config as cfg

MODULE = cfg.MODULE


@st.cache_data(show_spinner=False)
def _cached(name: str, kind: str, stamp):
    return store.load_json(MODULE, name) if kind == "json" else store.load_frame(MODULE, name)


def load(name: str, kind: str = "frame"):
    return _cached(name, kind, store.stamp(MODULE, name))


def _span(s: pd.Series, span: str) -> pd.Series:
    years = cfg.HISTORY_SPANS[span]
    return s if years is None or s.empty else s[s.index >= s.index.max() - pd.DateOffset(years=years)]


def _line(s: pd.Series, fmt: str, height: int = 230, y_range=None, fill: bool = False) -> go.Figure:
    fig = go.Figure(go.Scatter(x=s.index, y=s.values, mode="lines", line={"width": 2},
                               fill="tozeroy" if fill else None,
                               hovertemplate="%{x|%b %d, %Y}: %{y:" + fmt + "}<extra></extra>"))
    fig.update_layout(height=height, margin={"l": 0, "r": 0, "t": 4, "b": 0}, showlegend=False,
                      yaxis={"range": y_range} if y_range else {}, hovermode="x")
    return fig


# ================================================================= header
st.title("Credit")
summary = load("summary", "json")
if not summary:
    st.info("No credit data yet. Run `python run_jobs.py --only credit` from the hub folder "
            "(it runs credit-spread-analyzer's `scripts/publish_to_hub.py` in that project's venv).")
    st.stop()

if summary.get("demo"):
    st.warning("Published from the credit project's **cached data file** (demo mode), not a fresh download.")
st.caption(f"Data through {summary['as_of']} · from credit-spread-analyzer · "
           f"[open the full credit dashboard]({apps.launch_url(cfg.FULL_APP_URL)}) (starts it if needed)")

# ================================================================= headline tiles
stress, expo, fc = summary["stress"], summary["exposure"], summary["forecast"]
widening, decomp = summary.get("widening"), summary.get("decompression")
cols = st.columns(4)

with cols[0], st.container(border=True):
    p = stress.get("prob")
    band = ui.band_index(p, cfg.STRESS_CUTS)
    st.markdown("**Credit-stress regime**")
    ui.badge(cfg.STRESS_LABELS[band] if band is not None else "NO DATA",
             cfg.STRESS_COLORS[band] if band is not None else "grey")
    st.metric("P(stress)", "—" if p is None else f"{p:.0%}", label_visibility="collapsed")
    st.caption(f"{stress['n_states']}-state HMM on the Baa spread, refitted each January on past data "
               f"only and filtered forward (no look-ahead). Reading for {stress.get('date')}.")

with cols[1], st.container(border=True):
    w = expo.get("weight")
    st.markdown("**Overlay equity weight**")
    st.metric("Weight", "—" if w is None else f"{w:.0%}", label_visibility="collapsed")
    st.caption(f"min(1, {expo['target_vol']:.0%} ÷ recent S&P vol) × (1 − P(stress)); the rest in T-bills. "
               "Validated to cut drawdowns, not to add return.")

with cols[2], st.container(border=True):
    v = fc.get("bps")
    st.markdown(f"**{fc['horizon']}-day Baa spread forecast**")
    st.metric("Forecast", "—" if v is None else f"{v:+.1f} bps", label_visibility="collapsed")
    st.caption(f"`{fc['model']}` model, the best out-of-sample record at this horizon "
               f"(holdout from {fc['holdout_start'][:4]}). Forecast for {fc.get('date')}.")

with cols[3], st.container(border=True):
    st.markdown("**Tiers widening (20 days)**")
    if widening:
        st.metric("Widening", f"{widening['widening']} of {widening['total']}", label_visibility="collapsed")
        text = f"Rating tiers whose spread rose more than {widening['threshold_bp']:g} bps."
        if decomp:
            text += (f" CCC − B gap {decomp['value']:.0f} bps ({decomp['change_20d']:+.0f}), "
                     f"{decomp['percentile']:.0%} percentile of its history.")
        st.caption(text)
    else:
        st.caption("No rating-tier data.")

# ================================================================= spreads
st.subheader("Spreads")
cards = summary.get("spreads", {})
order = [c for c in cfg.SPREAD_LABELS if c in cards]
cols = st.columns(len(order) or 1)
for col, key in zip(cols, order):
    c = cards[key]
    col.metric(cfg.SPREAD_LABELS[key], f"{c['bps']:.0f} bps", f"{c['change_20d']:+.0f} bps (20d)",
               delta_color="inverse",
               help=f"{c['percentile']:.0%} of days since {c['since']} were at or below today's level. "
                    f"Last value {c['as_of']}.")

spreads = load("spreads_bps")
stress_hist = load("stress")
left, right = st.columns(2)
with left, st.container(border=True):
    c1, c2 = st.columns([1.4, 1], vertical_alignment="center")
    with c1:
        key = st.selectbox("Spread", order, format_func=cfg.SPREAD_LABELS.get, key="cr_spread",
                           label_visibility="collapsed")
    with c2:
        span = ui.choice("Span", list(cfg.HISTORY_SPANS), key="cr_span", default="10Y")
    if spreads is not None and key in spreads:
        ui.chart(_line(_span(spreads[key].dropna(), span), ".0f"), key="cr_spread_chart")
        st.caption(f"{cfg.SPREAD_LABELS[key]}, bps. ICE series come from FRED for about 3 years only, "
                   "except high yield, which the credit project splices back to 1996 from a licensed file.")

with right, st.container(border=True):
    st.markdown("**Real-time credit regime**")
    state_cols = [c for c in cfg.REGIME_STATES if stress_hist is not None and c in stress_hist]
    if state_cols:
        probs = stress_hist[state_cols].dropna(how="all")
        probs = probs[probs.index >= probs.index.max() - pd.DateOffset(years=cfg.HISTORY_SPANS[span])] \
            if cfg.HISTORY_SPANS[span] else probs
        baa = spreads[cfg.REGIME_SPREAD].reindex(probs.index) if spreads is not None and cfg.REGIME_SPREAD in spreads \
            else None
        fig = make_subplots(rows=2 if baa is not None else 1, cols=1, shared_xaxes=True, vertical_spacing=0.06,
                            row_heights=[0.62, 0.38] if baa is not None else [1.0])
        for col in state_cols:  # stacked, calm at the bottom
            label, color = cfg.REGIME_STATES[col]
            fig.add_trace(go.Scatter(x=probs.index, y=probs[col], name=label, mode="lines", stackgroup="p",
                                     line={"width": 0.5, "color": ui.PALETTE[color]},
                                     hovertemplate="%{y:.0%}<extra>" + label + "</extra>"), row=1, col=1)
        if baa is not None:
            fig.add_trace(go.Scatter(x=baa.index, y=baa.values, name=cfg.SPREAD_LABELS[cfg.REGIME_SPREAD],
                                     mode="lines", line={"width": 2, "color": ui.PALETTE["grey"]}, showlegend=False,
                                     hovertemplate="%{y:.0f} bp<extra>Baa spread</extra>"), row=2, col=1)
            fig.update_yaxes(title={"text": "Baa, bp", "font": {"size": 11}}, row=2, col=1)
        fig.update_yaxes(range=[0, 1], tickformat=".0%", row=1, col=1)
        fig.update_layout(height=330, margin={"l": 0, "r": 0, "t": 24, "b": 0}, hovermode="x unified",
                          legend={"orientation": "h", "y": 1.08, "x": 0})
        ui.chart(fig, key="cr_stress_chart")
        st.caption("What the model showed at each date: a 3-state HMM on the Baa spread, refitted every January "
                   "on past data only. Its probabilities are nearly all-or-nothing, and a January refit can switch "
                   "the regime with the spread unchanged (e.g. Jan 2011 and Jan 2012), because each refit redraws "
                   "where 'stressed' begins. Stress switched on in Aug 1998, early 2000 and Dec 2007, but only on "
                   "23 Mar 2020 for COVID: sudden shocks are left to the volatility part of the overlay.")

# ================================================================= tiers
st.subheader("Rating tiers")
tiers = summary.get("tiers") or []
if tiers:
    left, right = st.columns([1.1, 1])
    with left, st.container(border=True):
        t = pd.DataFrame(tiers)[["tier", "spread", "change", "percentile", "low", "high"]]
        ui.table(t, hide_index=True, column_config={
            "tier": "Tier",
            "spread": st.column_config.NumberColumn("Spread (bps)", format="%.0f"),
            "change": st.column_config.NumberColumn("20d change", format="%+.0f"),
            "percentile": st.column_config.ProgressColumn("Percentile", format="percent", min_value=0, max_value=1),
            "low": st.column_config.NumberColumn("Low", format="%.0f"),
            "high": st.column_config.NumberColumn("High", format="%.0f"),
        })
        st.caption(f"ICE BofA OAS by rating, history since {tiers[0]['history_start']} (FRED's ~3-year window), "
                   "so percentiles describe that window, not the long run.")
    tier_hist = load("tiers")
    with right, st.container(border=True):
        st.markdown("**CCC − B gap (decompression)**")
        if tier_hist is not None and {"CCC", "B"} <= set(tier_hist.columns):
            gap = (tier_hist["CCC"] - tier_hist["B"]).dropna()
            fig = _line(gap, ".0f", height=250)
            fig.add_hline(y=float(gap.mean()), line_dash="dot", line_width=1, opacity=0.5,
                          annotation_text="average", annotation_position="top left")
            ui.chart(fig, key="cr_decomp")
            st.caption("A rising gap means the weakest credits are cracking before the rest of the market.")

# ================================================================= fed liquidity
liq = summary.get("liquidity")
if liq:
    st.subheader("Fed liquidity")
    cols = st.columns(4)
    cols[0].metric("Net liquidity", f"${liq['net'] / 1000:,.2f}T",
                   f"{liq['net_change']:+,.0f}bn ({liq['net_change_pct']:+.1f}%, 13w)")
    cols[1].metric("Fed total assets", f"${liq['assets'] / 1000:,.2f}T", f"{liq['assets_change']:+,.0f}bn")
    cols[2].metric("Treasury General Account", f"${liq['tga']:,.0f}bn", f"{liq['tga_change']:+,.0f}bn",
                   delta_color="inverse")
    cols[3].metric("Overnight reverse repo", f"${liq['rrp']:,.0f}bn", f"{liq['rrp_change']:+,.0f}bn",
                   delta_color="inverse")
    st.caption(f"As of {liq['as_of']}. Context, not a signal: in the credit project's walk-forward tests, "
               "changes in net liquidity did not predict spread changes.")

# ================================================================= forecast history
forecast = load("forecast")
if forecast is not None and not forecast.empty:
    with st.expander(f"Recent {fc['horizon']}-day forecasts"):
        fig = go.Figure(go.Bar(x=forecast.index, y=forecast["forecast_bps"],
                               marker_color=[ui.PALETTE["red"] if v > 0 else ui.PALETTE["teal"]
                                             for v in forecast["forecast_bps"]],
                               hovertemplate="%{x|%b %d}: %{y:+.1f} bps<extra></extra>"))
        fig.update_layout(height=220, margin={"l": 0, "r": 0, "t": 4, "b": 0}, showlegend=False)
        ui.chart(fig, key="cr_forecast")
        st.caption("Predicted change in the Baa spread over the next 5 trading days, made at each date "
                   "(above zero = widening).")
