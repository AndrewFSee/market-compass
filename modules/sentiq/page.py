"""SentIQ page: what the model read in today's 8-Ks, earnings calls and Fed documents, how the collector is doing, and
where the research stands. Reads only what SentIQ publishes (scripts/publish_news_to_hub.py). No
returns on purpose (SentIQ's holdout stays unseen until its pre-registered looks)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import store, ui
from modules.sentiq import config as cfg

MODULE = cfg.MODULE


@st.cache_data(show_spinner=False)
def _cached(name: str, kind: str, stamp):
    return store.load_json(MODULE, name) if kind == "json" else store.load_frame(MODULE, name)


def load(name: str, kind: str = "frame"):
    return _cached(name, kind, store.stamp(MODULE, name))


@st.cache_data(show_spinner=False)
def _filings(stamp) -> pd.DataFrame | None:
    df = store.load_frame(MODULE, "filings")
    if df is None:
        return None
    for c in ("tradable_at", "published_at", "first_seen_at", "scored_at", "fades_by"):
        if c in df:
            df[c] = pd.to_datetime(df[c], utc=True).dt.tz_convert(cfg.ET)
    if "fades_by" not in df:
        df["fades_by"] = pd.NaT
    df["date"] = pd.to_datetime(df["date"])
    df["type"] = df["event_type"].map(cfg.EVENT_LABEL).fillna(df["event_type"])
    return df


def ago(ts, now: pd.Timestamp) -> str:
    if ts is None:
        return "never"
    m = (now - pd.Timestamp(ts)).total_seconds() / 60
    return f"{m:.0f} min ago" if m < 120 else (f"{m / 60:.1f} h ago" if m < 48 * 60 else f"{m / 1440:.0f} days ago")


def filing_table(v: pd.DataFrame, key: str) -> None:
    ui.table(pd.DataFrame({
        "Usable from (ET)": v["tradable_at"].dt.strftime("%Y-%m-%d %H:%M"),
        "Effect fades by (est.)": v["fades_by"].dt.strftime("%a %b %d").fillna("—"), "Ticker": v["ticker"],
        "Company": v["company"], "Doc": v["doc"], "Type": v["type"], "Sentiment": v["sentiment"],
        "Materiality": v["materiality"], "Surprise": v["surprise"], "Model's reading": v["rationale"],
        "Filing": v["url"]}),
        hide_index=True, key=key, column_config={
            "Effect fades by (est.)": st.column_config.TextColumn(help=cfg.FADES_HELP),
            "Materiality": st.column_config.TextColumn(help=cfg.MATERIALITY_HELP),
            "Sentiment": st.column_config.ProgressColumn(min_value=-1, max_value=1, format="%+.2f",
                                                         help="-1 very negative ... +1 very positive"),
            "Surprise": st.column_config.NumberColumn(format="%+.2f", help="Only when the text compares results "
                                                      "with expectations (about 1 release in 5)"),
            "Filing": st.column_config.LinkColumn(display_text="open")})


# ================================================================= header
st.title("Filings & Calls")
summary = load("summary", "json")
df = _filings(store.stamp(MODULE, "filings"))
if not summary or df is None:
    st.info("No SentIQ data yet. Run `python run_jobs.py --only sentiq` from the hub folder (it runs SentIQ's "
            "`scripts/publish_news_to_hub.py`, which reads SentIQ's store; nothing is fetched or scored).")
    st.stop()

as_of = pd.Timestamp(summary["as_of"]).tz_convert(cfg.ET)
st.caption(f"As of {as_of:%b %d, %Y %H:%M} ET (when the hub last refreshed this page). 8-Ks from EDGAR as they are "
           f"filed and earnings-call transcripts, each read once by {summary.get('model', 'Claude')} for the company "
           "it concerns: event type, sentiment, materiality. 'Usable from' is when the market could first act on it "
           "(after-hours filings move to the next open). This shows what the filings say, not trade signals: "
           "the research has not confirmed that any of it predicts returns (see Research status below).")

# ================================================================= health
h = load("health", "json") or {}
src = h.get("sources", {})
edgar = src.get("edgar", {})
last_ok = edgar.get("last_poll_ok_at")
stale = last_ok is None or (as_of - pd.Timestamp(last_ok)).total_seconds() / 60 > cfg.STALE_POLL_MINUTES
problems = list(h.get("problems") or [])
open_alerts = {s: a for s, v in src.items() for a in (v.get("open_alerts") or {})}
unresolved = h.get("scoring_unresolved_7d", 0)
c = st.columns(4)
c[0].metric("Collector", "stale" if stale else ("alert" if problems or open_alerts else "healthy"), border=True,
            help=f"Last successful EDGAR poll {ago(last_ok, as_of)}; {h.get('cycles_24h', 0)} cycles in 24 h, "
                 f"{h.get('cycles_failed_24h', 0)} failed")
med, mx = h.get("cycle_minutes_median"), h.get("cycle_minutes_max")
c[1].metric("Cycle time, 24 h", f"{med:.1f} min" if med is not None else "—", border=True,
            delta=f"max {mx:.0f} min" if mx is not None else None, delta_color="off",
            help="Poll + derive + live scoring, one collect run every ~2 min")
c[2].metric("New items, 24 h", f"{h.get('items_written_24h', 0):,}", border=True,
            help=f"Latest filing usable from {pd.Timestamp(summary['latest']).tz_convert(cfg.ET):%b %d %H:%M} ET"
            if summary.get("latest") else None)
c[3].metric("LLM spend this month", f"${h.get('spend_month_usd', 0):,.2f}", border=True,
            help=f"${h.get('spend_30d_usd', 0):,.2f} over the last 30 days")
if stale:
    ui.badge(f"No successful EDGAR poll for {ago(last_ok, as_of)} at refresh time: check the collector window", "red")
for p in problems:
    ui.badge(str(p), "amber")
if unresolved:
    ui.badge(f"{unresolved} filings from the last 7 days failed scoring and are still unscored (last error "
             f"{ago(h.get('scoring_last_error_at'), as_of)}): run `newsfeed score --dry-run` in SentIQ", "amber")

# ================================================================= latest filings
st.subheader("Latest filings")
c1, c2, c3 = st.columns([2, 3, 3])
with c1:
    days = cfg.WINDOWS[ui.choice("Window", list(cfg.WINDOWS), key="sq_days", default="1 week")]
with c2:
    groups = st.multiselect("Universe", cfg.GROUPS + ["S&P 500 (outside membership)"], default=cfg.GROUPS,
                            key="sq_groups")
with c3:
    types = st.multiselect("Event type", cfg.EVENT_TYPES, default=[t for t in cfg.EVENT_TYPES if t != "other"],
                           format_func=lambda t: cfg.EVENT_LABEL[t], key="sq_types")
c4, c5 = st.columns([2, 3])
with c4:
    relevant = st.toggle("About the company (relevance primary / secondary)", value=True, key="sq_rel")
with c5:
    docs = st.multiselect("Documents", ["8-K", "8-K/A", "Earnings call"], default=["8-K", "Earnings call"],
                          key="sq_docs")
since = as_of - pd.Timedelta(days=days)
v = df[(df["tradable_at"] >= since) & df["group"].isin(groups) & df["event_type"].isin(types)
       & df["doc"].isin(docs)]
if relevant:
    v = v[v["relevance"].isin(cfg.RELEVANT)]
if v.empty:
    st.caption("Nothing in this window with these filters.")
else:
    st.caption(f"{len(v):,} rows, newest first. One row per company a document is about (a filing naming two "
               "member companies appears twice).")
    filing_table(v.head(500), key="sq_latest")

# ================================================================= earnings board
st.subheader("Earnings and guidance: strongest readings")
c1, c2 = st.columns([2, 3])
with c1:
    edays = cfg.WINDOWS[ui.choice("Earnings window", list(cfg.WINDOWS), key="sq_edays", default="1 week")]
with c2:
    egroups = st.multiselect("Universe ", cfg.GROUPS, default=cfg.GROUPS, key="sq_egroups")
e = df[(df["tradable_at"] >= as_of - pd.Timedelta(days=edays)) & df["event_type"].isin(["earnings", "guidance"])
       & df["relevance"].isin(cfg.RELEVANT) & df["doc"].isin(["8-K", "8-K/A"]) & df["group"].isin(egroups)]
if e.empty:
    st.caption("No earnings or guidance releases in this window.")
else:
    l, r = st.columns(2)
    with l:
        st.markdown(f"**Most positive** ({len(e):,} releases in the window)")
        filing_table(e.sort_values("sentiment", ascending=False).head(cfg.TOP_N), key="sq_pos")
    with r:
        st.markdown("**Most negative**")
        filing_table(e.sort_values("sentiment").head(cfg.TOP_N), key="sq_neg")
    st.caption("Earnings-release sentiment is the project's best candidate: before the holdout, its rank correlation "
               "with the next two days' market-adjusted return was about +0.03 (test 1, nominal p 0.02, not "
               "significant after multiple-testing correction, and an upper bound because the model may remember "
               "2019–2026 outcomes). It is being tested on unseen data (H1); until then treat this as reading, "
               "not a ranking to trade.")

# ================================================================= tone over time
st.subheader("Tone of earnings releases over time")
daily = load("daily")
if daily is not None and not daily.empty:
    c1, c2 = st.columns([2, 3])
    with c1:
        rng = ui.choice("Range", list(cfg.TONE_RANGES), key="sq_tone_rng", default="3Y")
    with c2:
        tgroup = st.selectbox("Universe  ", cfg.GROUPS, key="sq_tone_group")
    d = daily[(daily["group"] == tgroup) & (daily["event_type"] == "earnings") & daily["doc"].isin(["8-K", "8-K/A"])]
    d = d.assign(date=pd.to_datetime(d["date"]), w=d["n"] * d["mean_sentiment"])
    wk = d.groupby(pd.Grouper(key="date", freq="W-FRI")).agg(n=("n", "sum"), w=("w", "sum"))
    wk = wk[wk["n"] > 0]
    wk["mean"] = wk["w"] / wk["n"]
    if cfg.TONE_RANGES[rng]:
        wk = wk[wk.index >= as_of.tz_localize(None) - pd.Timedelta(days=cfg.TONE_RANGES[rng])]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=wk.index, y=wk["n"], name="Releases per week", yaxis="y2",
                         marker_color=cfg.COLORS["bars"], opacity=0.6,
                         hovertemplate="%{y} releases<extra></extra>"))
    fig.add_trace(go.Scatter(x=wk.index, y=wk["mean"], name="Mean sentiment", mode="lines+markers",
                             line={"color": cfg.COLORS["line"], "width": 2}, marker={"size": 4},
                             hovertemplate="mean %{y:+.2f}<extra></extra>"))
    fig.update_layout(height=320, margin={"l": 0, "r": 0, "t": 30, "b": 0}, hovermode="x unified",
                      yaxis={"title": "mean sentiment", "zeroline": True},
                      yaxis2={"overlaying": "y", "side": "right", "showgrid": False, "title": "releases"},
                      legend={"orientation": "h", "y": 1.12, "x": 0})
    ui.chart(fig, key="sq_tone")
    st.caption("Weekly mean model sentiment of earnings 8-Ks (relevance primary / secondary), weeks ending Friday. "
               "Earnings seasons show as the tall bars. Weeks with few releases read lower mostly because of who "
               "reports then (off-calendar fiscal years, pre-announcements), not because news got worse, so compare "
               "seasons with the chart below. S&P 400 / 600 and the Nasdaq extras are collected only from 2026 on.")

    tm = load("tone_monthly")
    if tm is not None and not tm.empty and tm["yoy"].notna().any():
        tm = tm.assign(month=pd.to_datetime(tm["month"])).dropna(subset=["yoy"])
        if cfg.TONE_RANGES[rng]:
            tm = tm[tm["month"] >= as_of.tz_localize(None) - pd.Timedelta(days=cfg.TONE_RANGES[rng])]
        st.markdown("**S&P 500: change vs the same companies' releases a year earlier**")
        fig = go.Figure(go.Bar(
            x=tm["month"], y=tm["yoy"], customdata=tm[["n_pairs"]],
            marker_color=[cfg.COLORS["pos"] if y >= 0 else cfg.COLORS["neg"] for y in tm["yoy"]],
            hovertemplate="%{x|%b %Y}: %{y:+.2f} (%{customdata[0]} companies)<extra></extra>"))
        fig.update_layout(height=260, margin={"l": 0, "r": 0, "t": 10, "b": 0},
                          yaxis={"title": "change in sentiment", "zeroline": True})
        ui.chart(fig, key="sq_tone_yoy")
        st.caption("Each month: the average of (this release's sentiment − the same company's release about a year "
                   "earlier), months with at least 10 such pairs; the current month is partial. This removes the "
                   "seasonal mix of who reports. Whether it predicts the market was tested before the holdout "
                   "(test 12): it did not (correlation with next month's S&P 500 return −0.06, p 0.55).")

# ================================================================= Federal Reserve
@st.cache_data(show_spinner=False)
def _fed(stamp) -> pd.DataFrame | None:
    f = store.load_frame(MODULE, "fed")
    if f is None or f.empty:
        return None
    for c in ("tradable_at", "published_at", "first_seen_at", "scored_at"):
        f[c] = pd.to_datetime(f[c], utc=True).dt.tz_convert(cfg.ET)
    return f.sort_values("tradable_at", ascending=False)


st.subheader("Federal Reserve")
fed = _fed(store.stamp(MODULE, "fed"))
if fed is None:
    st.caption("No scored Fed documents published yet.")
else:
    fed_src = src.get("fed", {})
    stmt = fed[fed["doc"] == "FOMC statement"]
    mins = fed[fed["doc"] == "FOMC minutes"]
    talk = fed[fed["doc"].isin(["Speech", "Testimony"]) & fed["policy_relevance"].isin(cfg.FED_RELEVANT)
               & fed["stance"].notna()]
    recent = talk[talk["tradable_at"] >= as_of - pd.Timedelta(days=cfg.FED_TREND_DAYS)]
    c = st.columns(4)
    if not stmt.empty:
        s0 = stmt.iloc[0]
        c[0].metric("Latest FOMC statement", f"{s0['stance']:+.1f}", border=True,
                    delta=f"{s0['published_at']:%b %d, %Y} · {s0['rate_path']}", delta_color="off",
                    help=cfg.FED_STANCE_HELP)
    if not mins.empty:
        m0 = mins.iloc[0]
        c[1].metric("Latest minutes", f"{m0['stance']:+.1f}" if pd.notna(m0["stance"]) else "—", border=True,
                    delta=f"{m0['published_at']:%b %d, %Y}", delta_color="off", help=cfg.FED_STANCE_HELP)
    c[2].metric(f"Governors, last {cfg.FED_TREND_DAYS} days", f"{recent['stance'].mean():+.2f}"
                if not recent.empty else "—", border=True,
                delta=f"{len(recent)} policy speeches / testimony", delta_color="off",
                help="Mean stance of Governors' speeches and testimony with high or medium policy relevance")
    fed_ok = fed_src.get("last_poll_ok_at")
    c[3].metric("Last Fed poll", ago(fed_ok, as_of), border=True,
                help=f"Collected live since {pd.Timestamp(summary.get('fed_live_since')).tz_convert(cfg.ET):%b %d, %Y}"
                if summary.get("fed_live_since") else None)
    if fed_src.get("consecutive_failures"):
        ui.badge(f"Fed polls failing ({fed_src['consecutive_failures']} in a row): {fed_src.get('last_error')}",
                 "amber")

    frng = ui.choice("Range ", list(cfg.TONE_RANGES), key="sq_fed_rng", default="3Y")
    lo = as_of - pd.Timedelta(days=cfg.TONE_RANGES[frng]) if cfg.TONE_RANGES[frng] else None
    win = (lambda x: x if lo is None else x[x["tradable_at"] >= lo])
    trend = talk.sort_values("published_at").set_index("published_at")["stance"].rolling(
        f"{cfg.FED_TREND_DAYS}D").mean()
    trend = trend.groupby(level=0).last().reset_index().rename(columns={"published_at": "tradable_at"})
    fig = go.Figure()
    t = win(talk)
    fig.add_trace(go.Scatter(x=t["published_at"], y=t["stance"], mode="markers", name="Governor speech / testimony",
                             marker={"size": 5, "color": cfg.COLORS["muted"]},
                             text=t["speaker"] + ": " + t["title"] + "<br>" + t["rationale"].fillna(""),
                             hovertemplate="%{x|%Y-%m-%d} %{y:+.1f}<br>%{text}<extra></extra>"))
    tr = win(trend)
    fig.add_trace(go.Scatter(x=tr["tradable_at"], y=tr["stance"], mode="lines",
                             name=f"Governors, trailing {cfg.FED_TREND_DAYS}-day mean",
                             line={"color": cfg.COLORS["muted"], "width": 2, "dash": "dot"},
                             hovertemplate="%{x|%Y-%m-%d} %{y:+.2f}<extra></extra>"))
    m = win(mins)
    fig.add_trace(go.Scatter(x=m["published_at"], y=m["stance"], mode="markers", name="FOMC minutes",
                             marker={"size": 8, "symbol": "diamond", "color": cfg.COLORS["pos"]},
                             text=m["rationale"].fillna(""),
                             hovertemplate="%{x|%Y-%m-%d} minutes %{y:+.1f}<br>%{text}<extra></extra>"))
    pc = win(fed[fed["doc"].isin(cfg.PRESCONF_DOCS) & fed["stance"].notna()])
    fig.add_trace(go.Scatter(x=pc["published_at"], y=pc["stance"], mode="markers", name="Press conference",
                             marker={"size": 9, "symbol": "star", "color": cfg.COLORS["presconf"]},
                             text=pc["doc"] + " · " + pc["rationale"].fillna(""),
                             hovertemplate="%{x|%Y-%m-%d} %{y:+.1f}<br>%{text}<extra></extra>"))
    s = win(stmt)
    fig.add_trace(go.Scatter(x=s["published_at"], y=s["stance"], mode="lines+markers", name="FOMC statement",
                             line={"color": cfg.COLORS["line"], "width": 2, "shape": "hv"}, marker={"size": 7},
                             text=s["rate_path"] + " · " + s["rationale"].fillna(""),
                             hovertemplate="%{x|%Y-%m-%d} statement %{y:+.1f}<br>%{text}<extra></extra>"))
    fig.update_layout(height=340, margin={"l": 0, "r": 0, "t": 30, "b": 0},
                      yaxis={"range": [-1.05, 1.05], "title": "stance (dovish − / hawkish +)", "zeroline": True},
                      legend={"orientation": "h", "y": 1.12, "x": 0})
    ui.chart(fig, key="sq_fed_chart", zoom=True)
    st.caption("Each FOMC statement, press conference, set of minutes and policy-relevant Governor speech or "
               f"testimony read once by {summary.get('model', 'Claude')} (prompt "
               f"{summary.get('fed_prompt_version', 'fed_v1')}). Everything is plotted when its text was posted: "
               "minutes three weeks after the meeting; press conferences as the Chair's opening statement that "
               "afternoon and the full transcript with the Q&A one to three weeks later (earlier years: only the "
               "full transcript, dated by its last revision on the Fed's site). Collected live from Nov 18, 2026; "
               "earlier documents were scored afterwards for context, and the model may know how 2019–2026 turned "
               "out. Nothing here has been tested against market moves yet; a test will be pre-registered once "
               "enough live documents exist.")

    c1, c2, c3 = st.columns([2, 4, 3])
    with c1:
        fdays = cfg.WINDOWS[ui.choice("Fed window", list(cfg.WINDOWS), key="sq_fed_days", default="1 month")]
    with c2:
        fdocs = st.multiselect("Fed documents", cfg.FED_DOCS, default=cfg.FED_DOCS, key="sq_fed_docs")
    with c3:
        fpol = st.toggle("Policy-relevant only (high / medium)", value=False, key="sq_fed_rel")
    fv = fed[(fed["tradable_at"] >= as_of - pd.Timedelta(days=fdays)) & fed["doc"].isin(fdocs)]
    if fpol:
        fv = fv[fv["policy_relevance"].isin(cfg.FED_RELEVANT)]
    if fv.empty:
        st.caption("No Fed documents in this window with these filters.")
    else:
        num = {"format": "%+.1f", "help": cfg.FED_MACRO_HELP}
        ui.table(pd.DataFrame({
            "Released (ET)": fv["published_at"].dt.strftime("%Y-%m-%d %H:%M"),
            "Usable from (ET)": fv["tradable_at"].dt.strftime("%Y-%m-%d %H:%M"), "Document": fv["doc"],
            "Speaker": fv["speaker"], "Title": fv["title"], "Policy relevance": fv["policy_relevance"],
            "Stance": fv["stance"], "Rate path": fv["rate_path"], "Inflation": fv["inflation"],
            "Growth": fv["growth"], "Labor": fv["labor"], "Model's reading": fv["rationale"], "Link": fv["url"]}),
            hide_index=True, key="sq_fed_table", column_config={
                "Stance": st.column_config.ProgressColumn(min_value=-1, max_value=1, format="%+.1f",
                                                          help=cfg.FED_STANCE_HELP),
                "Rate path": st.column_config.TextColumn(help="Where the document points the policy rate next: "
                                                         "hike / hold / cut / unclear"),
                "Inflation": st.column_config.NumberColumn(**num), "Growth": st.column_config.NumberColumn(**num),
                "Labor": st.column_config.NumberColumn(**num),
                "Link": st.column_config.LinkColumn(display_text="open")})

# ================================================================= company lookup
st.subheader("Company lookup")
tickers = sorted(df["ticker"].dropna().unique())
pick = st.selectbox("Ticker", tickers, index=None, placeholder="Type a ticker", key="sq_ticker")
if pick:
    t = df[(df["ticker"] == pick) & df["relevance"].isin(cfg.RELEVANT)].sort_values("tradable_at")
    if t.empty:
        st.caption("No relevant scored documents for this ticker.")
    else:
        first = t.iloc[-1]
        st.caption(f"{first['company']} · {first['sector']} · {first['group']} · {len(t):,} documents since "
                   f"{t['tradable_at'].min():%Y-%m-%d}")
        fig = go.Figure()
        for typ, g in t.groupby("type"):
            fig.add_trace(go.Scatter(x=g["tradable_at"], y=g["sentiment"], mode="markers", name=typ,
                                     marker={"size": 8 if typ in ("earnings", "guidance") else 6},
                                     text=g["doc"] + ": " + g["rationale"].fillna(""),
                                     hovertemplate="%{x|%Y-%m-%d} %{y:+.2f}<br>%{text}<extra></extra>"))
        fig.update_layout(height=300, margin={"l": 0, "r": 0, "t": 30, "b": 0},
                          yaxis={"range": [-1.05, 1.05], "title": "sentiment"},
                          legend={"orientation": "h", "y": 1.15, "x": 0})
        ui.chart(fig, key="sq_ticker_chart", zoom=True)
        filing_table(t.sort_values("tradable_at", ascending=False).head(30), key="sq_ticker_table")

# ================================================================= research status
st.subheader("Research status")
ho = load("holdout", "json")
if ho:
    st.markdown(f"**Confirmation tests on unseen data** (holdout from {ho['start']}; each looked at once, on its date; "
                "counts so far are filings, not results)")
    for hyp in ho["hypotheses"]:
        frac = min(1.0, hyp["n_so_far"] / hyp["planned_n"]) if hyp["planned_n"] else 0.0
        st.markdown(f"**{hyp['id']}** {hyp['test']} — look {hyp['look']}; pass if {hyp['rule']}")
        st.progress(frac, text=f"{hyp['n_so_far']:,} of ~{hyp['planned_n']:,} planned events")
research = load("research")
if research is not None:
    with st.expander("Pre-registered tests so far (pre-holdout data, 2019 – June 2026)"):
        ui.table(research.rename(columns={"test": "Test", "date": "Date", "question": "Question",
                                          "primary": "Primary result (rank IC, p)", "verdict": "Verdict"}),
                 hide_index=True)
        st.caption("IC = rank correlation between the feature and the next h days' market-adjusted return; h1 / h2 "
                   "= 1 / 2 trading days (tests 7, 12 and 13 use the target named in the question). 'Nominal pass' = p < 0.05 for the primary cell but no discovery after the "
                   "Benjamini-Hochberg correction across each run's ~180 cells. Details: SentIQ's CLAUDE.md "
                   "decisions log.")

# ================================================================= collector details
with st.expander("Collector details (last 24 h)"):
    cyc = pd.DataFrame(h.get("cycles") or [])
    if not cyc.empty:
        cyc["started_at"] = pd.to_datetime(cyc["started_at"], utc=True).dt.tz_convert(cfg.ET)
        fig = go.Figure(go.Bar(x=cyc["started_at"], y=cyc["minutes"],
                               marker_color=[cfg.COLORS["neg"] if s != "ok" else
                                             (cfg.COLORS["line"] if w else cfg.COLORS["bars"])
                                             for s, w in zip(cyc["status"], cyc["written"])],
                               hovertemplate="%{x|%H:%M} %{y:.1f} min<extra></extra>"))
        fig.update_layout(height=220, margin={"l": 0, "r": 0, "t": 10, "b": 0}, yaxis={"title": "minutes"})
        ui.chart(fig, key="sq_cycles")
        st.caption("One bar per collect run; blue = ingested new items, red = failed. The live-coverage rule allows "
                   "up to 60 min between successful polls.")
    alerts = pd.DataFrame(h.get("alerts_7d") or [])
    if alerts.empty:
        st.caption("No alerts in the last 7 days.")
    else:
        alerts["raised_at"] = pd.to_datetime(alerts["raised_at"], utc=True).dt.tz_convert(cfg.ET).dt.strftime(
            "%Y-%m-%d %H:%M")
        st.markdown("**Alerts, last 7 days**")
        ui.table(alerts.rename(columns={"raised_at": "Raised (ET)", "source": "Source", "kind": "Kind",
                                        "message": "Message"}), hide_index=True)
