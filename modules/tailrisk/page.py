"""Tail-risk page. Reads only what tail-risk-scenario-engine publishes into the hub data folder."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import apps, store, ui
from modules.tailrisk import config as cfg

MODULE = cfg.MODULE


@st.cache_data(show_spinner=False)
def _cached(name: str, kind: str, stamp):
    return store.load_json(MODULE, name) if kind == "json" else store.load_frame(MODULE, name)


def load(name: str, kind: str = "frame"):
    return _cached(name, kind, store.stamp(MODULE, name))


# ================================================================= header
st.title("Tail Risk")
summary = load("summary", "json")
if not summary:
    st.info("No tail-risk data yet. Run `python run_jobs.py --only tailrisk` from the hub folder "
            "(it runs tail-risk-scenario-engine's `scripts/publish_to_hub.py` in that project's venv).")
    st.stop()

model, horizon = summary["model"], summary["model"]["horizon_days"]
port = ", ".join(f"{t} {w:.0%}" for t, w in summary["portfolio"].items())
st.caption(f"Portfolio: {port} · fit on daily data {summary['data_start']} to {summary['data_through']} · "
           f"run {summary['run_at'].replace('T', ' ')} · [open the full tail-risk app]({apps.launch_url(cfg.FULL_APP_URL)}) (starts it if needed)")
if summary.get("demo"):
    st.warning(f"Demo run with only {model['n_paths']:,} paths: tail estimates are noisy.")

# ================================================================= headline tiles
sim, hist = summary["simulated"], summary["historical"]
cols = st.columns(4)
for col, (lvl, key, label) in zip(cols, [("95%", "var", "VaR 95%"), ("95%", "cvar", "CVaR 95%"),
                                          ("99%", "var", "VaR 99%"), ("99%", "cvar", "CVaR 99%")]):
    with col, st.container(border=True):
        st.metric(f"{horizon}-day {label}", f"{sim[lvl][key]:.1%}",
                  f"{(sim[lvl][key] - hist[lvl][key]) * 100:+.1f} pts vs history", delta_color="inverse")
        st.caption(f"History, same definition: {hist[lvl][key]:.1%}")
st.caption(f"Loss not exceeded with 95% / 99% confidence (VaR) and the average loss beyond it (CVaR), over "
           f"{horizon} trading days, from {model['n_paths']:,} simulated paths. 'History' uses every overlapping "
           f"{horizon}-day window since {summary['data_start'][:4]}. Treat the figures as ±0.2 pts: refits on "
           "freshly downloaded prices move them about that much.")

crisis = summary.get("crisis_regime")
if crisis:
    band = ui.band_index(crisis["prob"], [0.3, 0.6])
    c1, c2 = st.columns([1, 3], vertical_alignment="center")
    with c1:
        ui.badge(["NORMAL REGIME", "MIXED", "CRISIS REGIME"][band], ["teal", "amber", "red"][band])
    c2.caption(f"P(crisis regime) today: {crisis['prob']:.0%} (long-run share {crisis['long_run_share']:.0%}). "
               f"The crisis state has {crisis['vol_ratio']:.1f}× the volatility; simulated paths switch "
               "between states as the fitted transition matrix says.")

# ================================================================= distribution & fan
fan, pnl = load("fan"), load("pnl_hist")
left, right = st.columns(2)
with left, st.container(border=True):
    st.markdown(f"**{horizon}-day return distribution**")
    if pnl is not None:
        var95 = -sim["95%"]["var"]
        colors = [ui.PALETTE["red"] if x <= var95 else ui.PALETTE["grey"] for x in pnl["bin_mid"]]
        fig = go.Figure(go.Bar(x=pnl["bin_mid"], y=pnl["unhedged"], marker_color=colors, marker_line_width=0,
                               hovertemplate="%{x:+.1%}: %{y:.1%} of paths<extra></extra>"))
        fig.add_vline(x=var95, line_dash="dot", line_width=1,
                      annotation_text=f"VaR 95% ({-var95:.1%})", annotation_position="top left")
        fig.update_layout(height=270, margin={"l": 0, "r": 0, "t": 20, "b": 0}, bargap=0.08, showlegend=False,
                          xaxis={"tickformat": ".0%"}, yaxis={"tickformat": ".0%"})
        ui.chart(fig, key="tr_hist")
        st.caption("Red bars: the worst 5% of outcomes, whose average is the CVaR 95%.")
with right, st.container(border=True):
    st.markdown("**Simulated portfolio paths**")
    if fan is not None:
        x = list(fan.index)
        fig = go.Figure([
            go.Scatter(x=x, y=fan["p95"], mode="lines", line={"width": 0}, hoverinfo="skip", showlegend=False),
            go.Scatter(x=x, y=fan["p5"], mode="lines", line={"width": 0}, fill="tonexty",
                       fillcolor="rgba(43,181,166,0.18)", name="5th–95th pct", hoverinfo="skip"),
            go.Scatter(x=x, y=fan["p75"], mode="lines", line={"width": 0}, hoverinfo="skip", showlegend=False),
            go.Scatter(x=x, y=fan["p25"], mode="lines", line={"width": 0}, fill="tonexty",
                       fillcolor="rgba(43,181,166,0.38)", name="25th–75th pct", hoverinfo="skip"),
            go.Scatter(x=x, y=fan["p50"], mode="lines", line={"width": 2, "color": ui.PALETTE["teal"]},
                       name="median", hovertemplate="day %{x}: %{y:+.1%}<extra>median</extra>"),
        ])
        fig.update_layout(height=270, margin={"l": 0, "r": 0, "t": 20, "b": 0}, hovermode="x",
                          xaxis={"title": "trading day"}, yaxis={"tickformat": ".0%"},
                          legend={"orientation": "h", "y": 1.12, "x": 0})
        ui.chart(fig, key="tr_fan")

# ================================================================= hedges & optimal
left, right = st.columns([1.3, 1])
with left, st.container(border=True):
    st.markdown("**Hedges, on the same scenarios**")
    rows = pd.DataFrame(summary["hedges"])
    if not rows.empty:
        rows["name"] = rows["name"].map(cfg.hedge_label)
        pct = lambda label: st.column_config.NumberColumn(label, format="percent")  # noqa: E731
        ui.table(rows, hide_index=True, column_config={
            "name": "Strategy", "expected_return": pct("Expected return"), "var_95": pct("VaR 95%"),
            "cvar_95": pct("CVaR 95%"), "cvar_99": pct("CVaR 99%")})
        iv = summary.get("hedge_implied_vol")
        st.caption(("Puts are priced with Black-Scholes at the current VIX "
                    f"({iv:.1%}), so their cost moves with the market. " if iv else "")
                   + "In money (simple) returns of a buy-and-hold portfolio, so the unhedged row differs slightly "
                     "from the log-return figures above; a put costs its premium in every scenario.")
opt = summary.get("optimal")
with right, st.container(border=True):
    st.markdown(f"**CVaR-optimal weights** (α = {opt['alpha']:.0%})" if opt else "**CVaR-optimal weights**")
    if opt:
        w = pd.DataFrame({"Current": pd.Series(summary["portfolio"]), "CVaR-optimal": pd.Series(opt["weights"])})
        ui.table(w.clip(lower=0), column_config={c: st.column_config.NumberColumn(c, format="percent") for c in w})
        st.caption(f"Minimises CVaR {opt['alpha']:.0%} over these scenarios (long-only, max weight per asset as "
                   f"configured): CVaR {opt['cvar']:.1%} vs {sim['95%']['cvar']:.1%} now, expected return "
                   f"{opt['expected_return']:+.1%} vs {sim['95%']['mean']:+.1%}.")

# ================================================================= stress
stress = summary.get("stress") or []
if stress:
    st.subheader("Stress scenarios")
    with st.container(border=True):
        t = pd.DataFrame([{"Scenario": r["name"], "What it does": r["description"],
                           "Expected return": r["95%"]["mean"], "VaR 95%": r["95%"]["var"],
                           "CVaR 95%": r["95%"]["cvar"], "CVaR 99%": r["99%"]["cvar"]} for r in stress])
        ui.table(t, hide_index=True, column_config={c: st.column_config.NumberColumn(c, format="percent")
                                                    for c in ("Expected return", "VaR 95%", "CVaR 95%", "CVaR 99%")})
        st.caption(f"Same portfolio and {horizon}-day horizon. Historical scenarios replay their window in 5-day "
                   "blocks; parametric ones re-run the simulation with shocked volatility, drift and correlations. "
                   "Scenario files live in the tail-risk project's configs/scenarios folder.")

with st.expander("Model and caveats"):
    st.markdown(
        f"- **Model:** {model['marginal'].replace('_', '-')} marginals, {model['volatility'].upper()} volatility, "
        f"{model['regime'].replace('_', ' ')} regimes, {model['dependence'].replace('_', ' ')} dependence; "
        f"{model['n_paths']:,} paths. Simulated excess kurtosis {sim['95%']['excess_kurtosis']:.1f} vs "
        f"{hist['95%']['excess_kurtosis']:.1f} in the data.\n"
        "- **Fixed Oct 2026:** the marginals and copula were fitted on raw returns while GARCH already models "
        "volatility clustering, which counted the fat tails twice (SPY tail parameter 2.4, infinite kurtosis; "
        "simulated kurtosis jumped between ~20 and ~120 run to run). They are now fitted on GARCH-standardized "
        "residuals. Regime paths now start from today's estimated regime instead of the long-run mix (~20% of "
        "paths had started in crisis). Drift is each asset's historical mean, not the GARCH location estimate.\n"
        "- The crisis regime raises volatility on top of GARCH, but only for moves into a more stressed "
        "state than today's (on a crisis day GARCH vol is already high). Without it the simulated deep tail is "
        "far thinner than history (CVaR 99% ~10% vs ~16%).\n"
        "- **Validated walk-forward** on 177 non-overlapping 21-day windows since 2012 (`tailrisk validate`): "
        "5 breaches of the 95% VaR where 8.9 were expected and 0 of the 99% (1.8 expected); both pass the "
        "Kupiec and Christoffersen tests, so it leans conservative."
    )
