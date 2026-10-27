"""Look-alikes page. Reads only what the analogs job publishes into the hub data folder."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import store, ui
from modules.analogs import config as cfg

MODULE = cfg.MODULE


@st.cache_data(show_spinner=False)
def _cached(name: str, kind: str, stamp):
    return store.load_json(MODULE, name) if kind == "json" else store.load_frame(MODULE, name)


def load(name: str, kind: str = "frame"):
    return _cached(name, kind, store.stamp(MODULE, name))


def pct(v, signed=True) -> str:
    return "—" if v is None else (f"{v:+.1f}%" if signed else f"{v:.1f}%").replace("-", "−")


# ================================================================= header
st.title("Look-alikes")
s = load("summary", "json")
if not s:
    st.info("No look-alike data yet. Run `python run_jobs.py --only market analogs` from the hub folder.")
    st.stop()

n = len(s["analogs"])
st.caption(f"Market state on {s['as_of']} compared with every trading day since {s['history_start'][:4]}; "
           f"the {n} closest distinct episodes (at least 3 months apart) and what the S&P 500 did next.")
if s.get("demo"):
    st.warning("Built from synthetic demo data.")
close = s.get("closeness")
if close is not None:
    if close >= 0.5:
        st.markdown(f"Today's look-alikes are **closer than {close:.0%}** of the matches found on past test dates, "
                    "so history has fair precedents for this state.")
    else:
        st.warning(f"Today's look-alikes are **further away than {1 - close:.0%}** of past matches: this state is "
                   "unusual, so read what followed with extra caution.")

# ================================================================= what followed
o = s["outcomes"]
r1, r3, vol, dd = o["ret_21"], o["ret_63"], o["vol_21"], o["mdd_21"]
st.subheader(f"What followed the {n} closest look-alikes")
cols = st.columns(4)
with cols[0], st.container(border=True):
    st.metric("S&P 500, next month (median)", pct(r1["analogs"]["median"]),
              f"{r1['analogs']['median'] - r1['all']['median']:+.1f} pts vs all days")
    st.caption(f"All days: {pct(r1['all']['median'])}. Range of look-alikes (10th–90th pct): "
               f"{pct(r1['analogs']['p10'])} to {pct(r1['analogs']['p90'])}, vs {pct(r1['all']['p10'])} to "
               f"{pct(r1['all']['p90'])} for all days.")
with cols[1], st.container(border=True):
    st.metric("Up a month later", f"{r1['analogs']['share_up']:.0%}",
              f"{(r1['analogs']['share_up'] - r1['all']['share_up']) * 100:+.0f} pts vs all days")
    st.caption(f"All days: {r1['all']['share_up']:.0%}. Over 3 months: {pct(r3['analogs']['median'])} median, "
               f"up {r3['analogs']['share_up']:.0%} of the time (all days {pct(r3['all']['median'])}, "
               f"{r3['all']['share_up']:.0%}).")
with cols[2], st.container(border=True):
    st.metric("Volatility, next month (median)", pct(vol["analogs"]["median"], signed=False),
              f"{vol['analogs']['median'] - vol['all']['median']:+.1f} pts vs all days", delta_color="inverse")
    st.caption(f"Annualised. All days: {pct(vol['all']['median'], signed=False)}; the last month's realised "
               f"volatility: {pct(s.get('trailing_vol'), signed=False)}.")
with cols[3], st.container(border=True):
    st.metric("Worst drop within the month", pct(dd["analogs"]["median"]),
              f"{dd['analogs']['median'] - dd['all']['median']:+.1f} pts vs all days")
    st.caption(f"Median of each look-alike's lowest close in the following month vs its start. "
               f"1 in 10 fell {pct(dd['analogs']['p10'])} or worse (all days {pct(dd['all']['p10'])}).")
st.caption(f"{n} episodes is a small sample: one or two of them can move these figures a lot.")

# ================================================================= paths
paths = load("paths")
left, right = st.columns([1.3, 1])
with left, st.container(border=True):
    st.markdown("**S&P 500 after each look-alike** (rebased to 100)")
    if paths is not None and not paths.empty:
        fig = go.Figure()
        for c in paths.columns:
            fig.add_trace(go.Scatter(x=paths.index, y=paths[c], mode="lines", showlegend=False,
                                     line={"width": 1, "color": ui.PALETTE["grey"]}, opacity=0.55,
                                     hovertemplate=f"{c}, day %{{x}}: %{{y:.1f}}<extra></extra>"))
        med = paths.median(axis=1)
        fig.add_trace(go.Scatter(x=med.index, y=med.values, mode="lines", name="median",
                                 line={"width": 3, "color": ui.PALETTE["teal"]},
                                 hovertemplate="day %{x}: %{y:.1f}<extra>median</extra>"))
        fig.add_hline(y=100, line_width=1, opacity=0.5)
        fig.add_vline(x=21, line_dash="dot", line_width=1, opacity=0.5, annotation_text="1 month",
                      annotation_position="top")
        fig.update_layout(height=330, margin={"l": 0, "r": 0, "t": 20, "b": 0}, hovermode="closest",
                          xaxis={"title": "trading days later"}, legend={"orientation": "h", "y": 1.08, "x": 0})
        ui.chart(fig, key="an_paths")
        st.caption("Grey: each look-alike episode. Teal: their median path.")
with right, st.container(border=True):
    st.markdown("**Today vs its look-alikes**")
    f = pd.DataFrame(s["features"])
    fmt = {r["key"]: r["fmt"] for r in s["features"]}
    show = pd.DataFrame({
        "Feature": f["label"] + f["used"].map({True: "", False: " (not used)"}),
        "Today": [fmt[k].format(v) if v is not None else "—" for k, v in zip(f["key"], f["value"])],
        "Look-alikes (median)": [fmt[k].format(v) if v is not None else "—"
                                 for k, v in zip(f["key"], f["analog_median"])],
        "Today's percentile": f["percentile"],
    })
    ui.table(show, hide_index=True, column_config={
        "Today's percentile": st.column_config.ProgressColumn(
            format="percent", min_value=0, max_value=1, help="Where today's value sits in its own history"),
    })
    st.caption("Each feature is used only once it would have been published (credit and the yield curve "
               "a day late, the liquidity gauge up to a week).")

# ================================================================= episodes
with st.expander(f"The {n} episodes"):
    a = pd.DataFrame(s["analogs"])
    ui.table(a[["date", "distance", "ret_21", "ret_63", "vol_21", "mdd_21"]], hide_index=True, column_config={
        "date": "Date",
        "distance": st.column_config.NumberColumn("Distance", format="%.2f",
                                                  help="Average gap from today in standard deviations; lower = closer"),
        "ret_21": st.column_config.NumberColumn("Next month", format="%+.1f%%"),
        "ret_63": st.column_config.NumberColumn("Next 3 months", format="%+.1f%%"),
        "vol_21": st.column_config.NumberColumn("Volatility", format="%.1f%%"),
        "mdd_21": st.column_config.NumberColumn("Worst drop", format="%+.1f%%"),
    })

# ================================================================= does it work?
c = s.get("check") or {}
st.subheader("Does this method work?")
with st.container(border=True):
    if c.get("n", 0) < 24:
        st.info("Not enough history to test the method yet.")
    else:
        def verdict(rho, sig):
            return "a real link" if sig else "no reliable link"

        st.markdown(
            f"Tested walk-forward on **{c['n']} non-overlapping months** since {c['start'][:4]}: at each test date "
            "the look-alikes were found using only data available then, and their median outcome was compared "
            "with what actually happened.")
        cols = st.columns(3)
        cols[0].metric("Direction (next-month return)", f"{c['ic_return']:+.2f}",
                       verdict(c["ic_return"], c["sig_return"]), delta_color="off")
        cols[1].metric("Volatility (next month)", f"{c['ic_vol']:+.2f}",
                       f"last month's vol alone: {c['ic_vol_naive']:+.2f}", delta_color="off")
        cols[2].metric("Volatility, beyond last month's", f"{c['ic_vol_extra']:+.2f}",
                       verdict(c["ic_vol_extra"], c["sig_vol_extra"]), delta_color="off")
        direction = ("They do carry a reliable signal for direction." if c["sig_return"] else
                     "**They don't predict direction**: treat the return figures above as context, not a forecast.")
        risk = ("For volatility they add information beyond simply assuming last month's volatility continues."
                if c["sig_vol_extra"] and c["ic_vol_extra"] > 0 else
                "For volatility they add nothing beyond assuming last month's volatility continues.")
        st.markdown(f"{direction} {risk}")
        st.caption("Figures are rank correlations between the look-alikes' median and the outcome; a link counts "
                   "as reliable when |value| × √(months − 1) > 1.96 (95%).")
