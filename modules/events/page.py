"""Events & odds page: the release calendar with what Kalshi and Polymarket price for each
number, the Fed path, and index / single-stock markets. Reads only what TickerLake publishes."""
from __future__ import annotations

import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import store, ui
from modules.events import config as cfg

MODULE = cfg.MODULE


@st.cache_data(show_spinner=False)
def _cached(module: str, name: str, kind: str, stamp):
    return store.load_json(module, name) if kind == "json" else store.load_frame(module, name)


def load(name: str, kind: str = "frame", module: str = MODULE):
    return _cached(module, name, kind, store.stamp(module, name))


def fmt_value(v, pct: bool) -> str:
    if v is None or pd.isna(v):
        return "—"
    if pct:
        return f"{v:+.2f}%" if abs(v) < 1 else f"{v:.2f}%"
    if abs(v) >= 10_000:
        return f"{v / 1000:,.0f}k"
    return f"{v:,.2f}" if abs(v) < 100 else f"{v:,.0f}"


def says(r: pd.Series) -> str:
    """One market's answer in a phrase."""
    if r["kind"] == "ladder":
        strikes = json.loads(r["detail"]).get("strikes") or []
        if r.get("below_range") and strikes:
            return f"below {fmt_value(strikes[0], r['pct'])}"
        if r.get("above_range") and strikes:
            return f"above {fmt_value(strikes[-1], r['pct'])}"
        return f"median {fmt_value(r['median'], r['pct'])}"
    if r["kind"] in ("outcomes", "binary") and pd.notna(r.get("top_prob")):
        return f"{r['top']} ({r['top_prob']:.0%})"
    return r["kind"]


def ladder_chart(r: pd.Series, spot: float | None = None, key: str = "") -> None:
    d = json.loads(r["detail"])
    if not d.get("strikes"):
        return
    k, p = d["strikes"], [x * 100 for x in d["p_above"]]
    fig = go.Figure(go.Scatter(x=k, y=p, mode="lines+markers", line={"width": 2}, marker={"size": 8},
                               hovertemplate="above %{x}: %{y:.0f}%<extra></extra>"))
    if pd.notna(r.get("median")):
        fig.add_vline(x=r["median"], line_dash="dash", line_color=ui.PALETTE["grey"],
                      annotation_text=f"median {fmt_value(r['median'], r['pct'])}", annotation_position="bottom right")
    if spot:
        fig.add_vline(x=spot, line_color=ui.PALETTE["amber"], annotation_text=f"last {spot:,.2f}",
                      annotation_position="top left")
    fig.update_layout(height=250, margin={"l": 0, "r": 0, "t": 34, "b": 0}, yaxis={"range": [0, 105], "ticksuffix": "%"},
                      xaxis={"ticksuffix": "%" if r["pct"] else ""},
                      title={"text": "Probability the value ends above each level", "font": {"size": 13}})
    ui.chart(fig, key=f"ladder_{key}")


def outcomes_chart(r: pd.Series, key: str = "") -> None:
    d = json.loads(r["detail"])
    if not d.get("outcomes"):
        return
    s = pd.Series(d["probs"], index=d["outcomes"]).sort_values()
    fig = go.Figure(go.Bar(x=s.values * 100, y=s.index, orientation="h", marker_color=ui.PALETTE["teal"],
                           hovertemplate="%{y}: %{x:.0f}%<extra></extra>"))
    fig.update_layout(height=max(160, 28 * len(s)), margin={"l": 0, "r": 0, "t": 10, "b": 0},
                      xaxis={"ticksuffix": "%"})
    ui.chart(fig, key=f"outcomes_{key}")


def touch_chart(r: pd.Series, spot: float | None, key: str = "") -> None:
    d = json.loads(r["detail"])
    up, down = d.get("up") or [], d.get("down") or []
    fig = go.Figure()
    if down:
        fig.add_bar(x=[k for k, _ in down], y=[p * 100 for _, p in down], name="Trades down to", marker_color=ui.PALETTE["red"],
                    hovertemplate="down to %{x}: %{y:.0f}%<extra></extra>")
    if up:
        fig.add_bar(x=[k for k, _ in up], y=[p * 100 for _, p in up], name="Trades up to", marker_color=ui.PALETTE["teal"],
                    hovertemplate="up to %{x}: %{y:.0f}%<extra></extra>")
    if spot:
        fig.add_vline(x=spot, line_color=ui.PALETTE["amber"], annotation_text=f"last {spot:,.2f}")
    fig.update_layout(height=240, margin={"l": 0, "r": 0, "t": 24, "b": 0}, yaxis={"range": [0, 100], "ticksuffix": "%"},
                      legend={"orientation": "h", "y": 1.15},
                      title={"text": "Probability of trading at each price before expiry", "font": {"size": 13}})
    ui.chart(fig, key=f"touch_{key}")


def short_label(r: pd.Series) -> str:
    if r["venue"] == "kalshi" and r["series"] in cfg.SERIES_LABEL:
        return cfg.SERIES_LABEL[r["series"]]
    title = str(r["event_title"]).split(" - ")[0].rstrip("?")
    return title if len(title) <= 28 else title[:27] + "…"


def venue_link(r: pd.Series) -> str:
    name = "Kalshi" if r["venue"] == "kalshi" else "Polymarket"
    return f"[{name}]({r['url']})" if r.get("url") else name


# ================================================================= header
st.title("Events & odds")
summary = load("summary", "json")
if not summary:
    st.info("No calendar or prediction-market data yet. Run `python run_jobs.py --only events` from the hub "
            "folder (it runs TickerLake's `scripts/publish_events_to_hub.py`; TickerLake's `econ_calendar` and "
            "`prediction_markets` stages collect the data).")
    st.stop()

cal, odds, fed = load("calendar"), load("odds"), load("fed")
assets, other, history = load("assets"), load("other"), load("history")
st.caption(f"Odds as of {pd.Timestamp(summary['snapshot_date']):%b %d, %Y} from Kalshi and Polymarket, collected daily "
           f"since {pd.Timestamp(summary['first_snapshot']):%b %d, %Y}. Release dates from FRED's calendar; FOMC and "
           "ISM dates from when Kalshi's markets on them close.")

# ================================================================= calendar
st.subheader("Economic calendar")
if cal is None or cal.empty:
    st.info("No upcoming releases.")
else:
    horizon = pd.Timestamp(summary["snapshot_date"]) + pd.Timedelta(days=cfg.CALENDAR_DAYS)
    shown = cal[pd.to_datetime(cal["release_date"]) <= horizon].copy()
    by_release = {}
    if odds is not None and not odds.empty:
        for (key, d), g in odds.groupby(["release_key", "release_date"]):
            by_release[(key, pd.Timestamp(d))] = " · ".join(
                f"{'K' if r['venue'] == 'kalshi' else 'PM'} {short_label(r)}: {says(r)}"
                for _, r in g.sort_values("volume", ascending=False).iterrows())
    shown["Markets say"] = [by_release.get((k, pd.Timestamp(d)), "") for k, d in zip(shown["release_key"], shown["release_date"])]
    shown["Date"] = pd.to_datetime(shown["release_date"]).dt.strftime("%a %b %d")
    shown["Importance"] = shown["importance"].map(cfg.IMPORTANCE_ICON).fillna("")
    ui.table(shown[["Date", "time_et", "name", "Importance", "Markets say"]].rename(
        columns={"time_et": "Time (ET)", "name": "Release"}), hide_index=True, height=35 * (len(shown) + 1) + 3,
        column_config={"Date": st.column_config.TextColumn(width="small"),
                       "Time (ET)": st.column_config.TextColumn(width="small"),
                       "Importance": st.column_config.TextColumn(width="small"),
                       "Release": st.column_config.TextColumn(width="medium"),
                       "Markets say": st.column_config.TextColumn(width="large")})
    st.caption(f"Next {cfg.CALENDAR_DAYS} days. K = Kalshi, PM = Polymarket. A median is the level the market "
               "gives even odds of being exceeded; for named outcomes, the likeliest one and its probability.")

    if odds is not None and not odds.empty:
        options = (odds.sort_values(["release_date", "volume"], ascending=[True, False])
                   .drop_duplicates(["release_key", "release_date"]))
        labels = {f"{pd.Timestamp(r['release_date']):%b %d} · {cal.loc[cal['release_key'] == r['release_key'], 'name'].iloc[0]}":
                  (r["release_key"], r["release_date"]) for _, r in options.iterrows()
                  if (cal["release_key"] == r["release_key"]).any()}
        pick = st.selectbox("Release detail", list(labels), key="ev_release")
        key, day = labels[pick]
        for i, (_, r) in enumerate(odds[(odds["release_key"] == key) & (odds["release_date"] == day)]
                                   .sort_values("volume", ascending=False).iterrows()):
            with st.container(border=True):
                vol = f"${r['volume']:,.0f}" if r["venue"] == "polymarket" else f"{r['volume']:,.0f} contracts"
                st.markdown(f"**{r['event_title']}** · {venue_link(r)} · {says(r)} · traded {vol}")
                if r["kind"] == "ladder":
                    ladder_chart(r, key=f"rel{i}")
                elif r["kind"] in ("outcomes", "multi"):
                    outcomes_chart(r, key=f"rel{i}")
                h = history[(history["venue"] == r["venue"]) & (history["event_id"] == r["event_id"])] \
                    if history is not None and not history.empty else pd.DataFrame()
                col = "median" if r["kind"] == "ladder" else "top_prob"
                if len(h.dropna(subset=[col])) >= 2:
                    fig = go.Figure(go.Scatter(x=pd.to_datetime(h["snapshot_date"]), y=h[col], mode="lines+markers"))
                    fig.update_layout(height=160, margin={"l": 0, "r": 0, "t": 22, "b": 0},
                                      title={"text": "Implied median by day" if col == "median"
                                             else f"P({r['top']}) by day", "font": {"size": 13}})
                    ui.chart(fig, key=f"hist{i}")

# ================================================================= Fed
st.subheader("Fed meetings")
if fed is None or fed.empty:
    st.info("No Fed-decision markets open.")
else:
    k = fed[fed["venue"] == "kalshi"]
    base = k if not k.empty else fed.drop_duplicates("meeting")
    fig = go.Figure()
    for side in ("cut", "hold", "hike"):
        fig.add_bar(y=pd.to_datetime(base["meeting"]).dt.strftime("%b %d, %Y"), x=base[side] * 100, name=side.title(),
                    orientation="h", marker_color=ui.PALETTE[cfg.FED_COLORS[side]],
                    hovertemplate=f"{side}: %{{x:.0f}}%<extra></extra>")
    fig.update_layout(barmode="stack", height=max(180, 30 * len(base)), margin={"l": 0, "r": 0, "t": 10, "b": 0},
                      xaxis={"range": [0, 100], "ticksuffix": "%"}, yaxis={"autorange": "reversed"},
                      legend={"orientation": "h", "y": 1.1, "traceorder": "normal"})
    ui.chart(fig, key="fed_path")
    wide = fed.pivot_table(index="meeting", columns="venue", values=["cut", "hold", "hike"])
    wide = wide[[(side, v) for side in ("cut", "hold", "hike") for v in ("kalshi", "polymarket") if (side, v) in wide]]
    wide.columns = [f"{side.title()} ({'Kalshi' if v == 'kalshi' else 'Polymarket'})" for side, v in wide.columns]
    wide.index = pd.to_datetime(wide.index).strftime("%b %d, %Y")
    ui.table(wide.map(lambda v: "" if pd.isna(v) else f"{v:.0%}"))
    st.caption("Probability of each decision at each meeting, the outcomes on each venue summed into cut, hold "
               "and hike. The chart uses Kalshi, which lists more meetings.")

# ================================================================= indices & stocks
st.subheader("Indices & stocks")
if assets is None or assets.empty:
    st.info("No index or stock markets open.")
else:
    perf = load("constituents_perf", module="market")
    etf = load("etf_returns", module="market")
    spot = {}
    if perf is not None:
        spot.update(perf.set_index("symbol")["last"].to_dict())
    if etf is not None and "last" in etf:
        spot.update(etf["last"].to_dict())
    order = ["S&P 500", "SPY", "Nasdaq-100"]
    names = sorted(assets["underlying"].unique(), key=lambda u: (order.index(u) if u in order else 9, u))
    pick = st.selectbox("Underlying", names, key="ev_asset")
    last = spot.get(pick)
    rows = assets[assets["underlying"] == pick].sort_values("close_time")
    st.caption(f"Last close {last:,.2f}." if last else "No last price in the hub for this one.")
    for i, (_, r) in enumerate(rows.iterrows()):
        with st.container(border=True):
            exp = pd.Timestamp(r["close_time"]).tz_convert("America/New_York")
            implied = ""
            if r["kind"] == "ladder" and pd.notna(r.get("median")) and last:
                implied = f" ({r['median'] / last - 1:+.1%} from the last close)"
            st.markdown(f"**{r['event_title']}** · expires {exp:%b %d %I:%M %p} ET · {venue_link(r)} · "
                        f"{says(r)}{implied}")
            if r["kind"] == "ladder":
                ladder_chart(r, spot=last, key=f"a{i}")
            elif r["kind"] == "touch":
                touch_chart(r, spot=last, key=f"a{i}")
            elif r["kind"] == "binary":
                st.metric("Probability", f"{r['top_prob']:.0%}")

# ================================================================= other
if other is not None and not other.empty:
    st.subheader("Other US macro markets")
    view = other.assign(**{
        "Market": other["event_title"],
        "Says": [says(r) if r["kind"] != "multi" else "several independent levels" for _, r in other.iterrows()],
        "Traded 24h": other["volume_24h"].map(lambda v: "" if pd.isna(v) else f"${v:,.0f}"),
        "Link": other["url"],
    })[["Market", "Says", "Traded 24h", "Link"]]
    ui.table(view, hide_index=True, column_config={"Link": st.column_config.LinkColumn(display_text="open")})

with st.expander("How to read these numbers"):
    st.markdown(
        "- A contract paying $1 if something happens trades near its probability, minus fees and the spread. "
        "The page uses the bid/ask midpoint when the spread is 15 cents or less, else the last trade.\n"
        "- Thin markets move on small orders. Compare the traded amounts before trusting a number, and prefer "
        "events traded on both venues.\n"
        "- Kalshi counts contracts (each pays $1), Polymarket dollars.\n"
        "- These are the markets' odds, not forecasts this dashboard has tested. The history starts with the "
        "first daily snapshot, so whether they beat the usual consensus can be measured once releases accumulate.")
