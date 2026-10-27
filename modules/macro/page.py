"""Macro regime page. Reads only what macro-regime-nowcaster publishes into the hub data folder."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import store, ui
from modules.macro import config as cfg

MODULE = cfg.MODULE


@st.cache_data(show_spinner=False)
def _cached(name: str, kind: str, stamp):
    return store.load_json(MODULE, name) if kind == "json" else store.load_frame(MODULE, name)


def load(name: str, kind: str = "frame"):
    return _cached(name, kind, store.stamp(MODULE, name))


# ================================================================= header
st.title("Macro Regime")
summary = load("summary", "json")
if not summary:
    st.info("No macro data yet. Run `python run_jobs.py --only macro` from the hub folder "
            "(it runs macro-regime-nowcaster's `scripts/publish_to_hub.py` in that project's venv).")
    st.stop()

now, panel_info = summary.get("nowcast"), summary.get("panel")
st.caption(f"Published {summary['run_at'].replace('T', ' ')} · from macro-regime-nowcaster · "
           f"[open the full macro dashboard]({cfg.FULL_APP_URL})")
if now is None:
    st.warning("No live nowcast on the last run (demo mode or the run failed); showing the walk-forward panel only.")

# ================================================================= headline tiles
if now:
    as_of = (now.get("signal_as_of") or {}).get("ensemble")
    p = now["recession_probability"]
    band = ui.band_index(p, cfg.RECESSION_CUTS)
    cols = st.columns([1, 1, 1.4])
    with cols[0], st.container(border=True):
        st.markdown("**Recession probability**")
        ui.badge(cfg.RECESSION_LABELS[band], cfg.RECESSION_COLORS[band])
        st.metric("P(recession)", f"{p:.1%}", label_visibility="collapsed")
        st.caption(f"Ensemble of the signals below, for {as_of or 'the latest month'}. A coincident detector: "
                   "it says whether a recession is under way, not whether one is coming.")
    with cols[1], st.container(border=True):
        st.markdown("**GDP nowcast**")
        st.metric("GDP", f"{now['gdp_nowcast']:+.1f}%", label_visibility="collapsed")
        st.caption(f"Real GDP growth, annualised. 90% interval {now['gdp_ci_lower']:+.1f}% to "
                   f"{now['gdp_ci_upper']:+.1f}%: read it as a direction, not a number.")
    with cols[2], st.container(border=True):
        st.markdown("**Signals**")
        weights = now.get("weights", {})
        detail = now.get("ensemble_detail", {})
        rows = [{"Signal": cfg.SIGNAL_LABELS.get(k, k), "P(recession)": detail[k], "Weight": weights.get(k, 0.0)}
                for k in cfg.SIGNAL_LABELS if k in detail]
        rows.sort(key=lambda r: -r["Weight"])
        ui.table(pd.DataFrame(rows), hide_index=True, column_config={
            "P(recession)": st.column_config.NumberColumn(format="percent"),
            "Weight": st.column_config.NumberColumn(format="percent")})
        st.caption("Weights were set from out-of-sample results; zero-weight signals are shown for context.")

# ================================================================= history
wf = load("walk_forward")
st.subheader("Recession probability, as it read at the time")
if wf is None or "p_recession" not in wf:
    st.info("No walk-forward panel published. Run `scripts/build_features.py` in macro-regime-nowcaster.")
else:
    with st.container(border=True):
        span = ui.choice("Span", list(cfg.HISTORY_SPANS), key="mc_span", default="All")
        s = wf["p_recession"].dropna()
        years = cfg.HISTORY_SPANS[span]
        if years:
            s = s[s.index >= s.index.max() - pd.DateOffset(years=years)]
        fig = go.Figure(go.Scatter(x=s.index, y=s.values, mode="lines", line={"width": 2}, fill="tozeroy",
                                   hovertemplate="%{x|%b %Y}: %{y:.0%}<extra></extra>"))
        for start, end in cfg.NBER_RECESSIONS:
            if pd.Timestamp(end) >= s.index.min():
                fig.add_vrect(x0=start, x1=end, fillcolor=ui.PALETTE["grey"], opacity=0.25, line_width=0,
                              layer="below")
        fig.update_layout(height=280, margin={"l": 0, "r": 0, "t": 4, "b": 0}, showlegend=False,
                          yaxis={"range": [0, 1], "tickformat": ".0%"}, hovermode="x")
        ui.chart(fig, key="mc_history")
        built = datetime.fromisoformat(panel_info["built"])
        st.caption(f"One refit per month, keeping only that fit's final row, so no point uses later data. "
                   f"Grey bands are NBER recessions. {panel_info['rows']} months through "
                   f"{panel_info['through'][:7]}, panel built {built:%b %d, %Y}.")
        if (datetime.now() - built).days > cfg.PANEL_STALE_DAYS:
            st.warning("The walk-forward panel is more than a month old. Rebuild it with "
                       "`python scripts/build_features.py` in macro-regime-nowcaster.")

# ================================================================= factors
if now and now.get("factor_values"):
    st.subheader("Latent factors")
    left, right = st.columns([1.2, 1])
    with left, st.container(border=True):
        f = pd.Series(now["factor_values"]).rename(index=cfg.FACTOR_LABELS).sort_values()
        fig = go.Figure(go.Bar(x=f.values, y=f.index, orientation="h", marker_color=ui.PALETTE["teal"],
                               hovertemplate="%{y}: %{x:+.2f}<extra></extra>"))
        fig.add_vline(x=0, line_width=1, opacity=0.6)
        fig.update_layout(height=240, margin={"l": 0, "r": 0, "t": 4, "b": 0}, showlegend=False)
        ui.chart(fig, key="mc_factors")
        st.caption("Latest Kalman-filtered factor values (standardised), extracted from about 75 FRED series.")
    with right, st.container(border=True):
        st.markdown("**Factor history (walk-forward)**")
        names = [k for k in cfg.FACTOR_LABELS if f"factor_{k}" in (wf.columns if wf is not None else [])]
        if names:
            pick = st.selectbox("Factor", names, format_func=cfg.FACTOR_LABELS.get, key="mc_factor",
                                label_visibility="collapsed")
            h = wf[f"factor_{pick}"].dropna()
            h = h[h.index >= h.index.max() - pd.DateOffset(years=25)]
            fig = go.Figure(go.Scatter(x=h.index, y=h.values, mode="lines", line={"width": 2},
                                       hovertemplate="%{x|%b %Y}: %{y:+.2f}<extra></extra>"))
            fig.add_hline(y=0, line_width=1, opacity=0.5)
            fig.update_layout(height=190, margin={"l": 0, "r": 0, "t": 4, "b": 0}, showlegend=False, hovermode="x")
            ui.chart(fig, key="mc_factor_hist")

# ================================================================= caveats
with st.expander("What this model can and can't do"):
    st.markdown(
        "Measured on a 717-point monthly walk-forward (1967 to 2026, eight recessions):\n\n"
        "- **Detects recessions in real time** well (AUC 0.94) and beats professional forecasters at the "
        "current horizon.\n"
        "- **Not significantly better than CFNAI alone**, the free index it partly uses; since 1990, no edge.\n"
        "- **Not a forecaster:** 12 months out it is at chance. It also showed no skill on forward equity "
        "returns or drawdowns.\n"
        "- **Missed COVID**, a two-month stop that is below the monthly data's resolution.\n\n"
        "The live reading (tiles) and the latest panel row can differ for the same month: the live run "
        "uses today's revised data and a fresh fit."
    )
