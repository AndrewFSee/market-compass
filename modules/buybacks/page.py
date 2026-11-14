"""Buybacks page: what S&P 500 companies have been buying back (from SEC filings), the authorization
they have left, and which ones are estimated to be in their buyback blackout. Reads only what
TickerLake publishes."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import store, ui
from modules.buybacks import config as cfg

MODULE = cfg.MODULE
SECTOR_SHORT = {"Information Technology": "Tech", "Communication Services": "Comm", "Consumer Discretionary": "Discretionary",
                "Consumer Staples": "Staples", "Health Care": "Health", "Real Estate": "Real estate"}


@st.cache_data(show_spinner=False)
def _cached(module: str, name: str, kind: str, stamp):
    return store.load_json(module, name) if kind == "json" else store.load_frame(module, name)


def load(name: str, kind: str = "frame"):
    return _cached(MODULE, name, kind, store.stamp(MODULE, name))


@st.cache_data(show_spinner=False)
def _news(name: str, kind: str, stamp):
    return store.load_json("buyback_news", name) if kind == "json" else store.load_frame("buyback_news", name)


def news(name: str, kind: str = "frame"):
    return _news(name, kind, store.stamp("buyback_news", name))


KIND_LABEL = {"new_program": "new program", "increase": "increase", "replacement": "replacement",
              "accelerated_repurchase": "accelerated (ASR)", "tender_offer": "tender offer"}


def bn(v) -> str:
    return "—" if v is None or pd.isna(v) else f"${v / 1e9:,.0f}bn"


# ================================================================= header
st.title("Buybacks")
summary = load("summary", "json")
if not summary:
    st.info("No buyback data yet. Run `python run_jobs.py --only buybacks` from the hub folder (it runs TickerLake's "
            "`scripts/publish_buybacks_to_hub.py`; the release-date history comes from TickerLake's "
            "`scripts/backfill_earnings_releases.py`).")
    st.stop()

stocks, share = load("stocks"), load("blackout_share")
as_of = pd.Timestamp(summary["as_of"])
st.caption(f"As of {as_of:%b %d, %Y}. Companies announce how much they *may* buy back; what they actually bought "
           "is reported only afterwards, in each 10-Q / 10-K, so the dollar figures trail by up to a quarter. Blackout "
           "windows are never disclosed: they are estimated from each company's fiscal quarter-ends and earnings dates.")

soon_end = as_of + pd.offsets.BDay(cfg.REOPEN_SOON_BDAYS)
soon = stocks[stocks["blackout"].fillna(False).astype(bool) & (pd.to_datetime(stocks["reopens"]) <= soon_end)]
c = st.columns(4)
c[0].metric("Bought back, last 12 months", bn(summary["buybacks_ttm"]), border=True,
            help=f"Sum of the latest four reported quarters, {summary['with_buybacks']} of {summary['members']} members")
c[1].metric("Authorization left", bn(summary["remaining_auth"]), border=True,
            help=f"Remaining under announced programs, as last reported by {summary['with_auth']} members")
cap_share = summary.get("blackout_share_cap")
c[2].metric("In estimated blackout", f"{cap_share:.0%} of cap" if cap_share is not None else
            f"{summary['blackout_share_count']:.0%}", border=True,
            help=f"{summary['blackout_share_count']:.0%} of members by count")
c[3].metric("Reopening within 2 weeks", f"{len(soon)}", border=True,
            help=f"Members estimated in blackout whose window reopens within {cfg.REOPEN_SOON_BDAYS} trading days, by "
                 f"{soon_end:%b %d} (two trading days after their next earnings release)")

# ================================================================= announcements
ann = news("announcements")
if ann is not None and not ann.empty:
    ann = ann.copy()
    ann["tradable_at"] = pd.to_datetime(ann["tradable_at"], utc=True).dt.tz_convert("America/New_York")
    ann["ticker"] = ann["tickers"].fillna("").str.split(",").str[0]
    ann["amount_usd"] = pd.to_numeric(ann["amount_usd"], errors="coerce")   # None -> NaN (blank, not "None")
    caps = stocks.set_index("symbol")["mcap"]
    ann["pct_cap"] = ann["amount_usd"] / ann["ticker"].map(caps)
    ann["member"] = ann["ticker"].isin(set(stocks["symbol"]))
st.subheader("Recently announced")
if ann is None or ann.empty:
    st.info("No classified announcements yet. They come from 8-Ks that SentIQ collects (job `buyback_news`), "
            "read by Claude once each (job `buyback_news_classify`).")
else:
    c1, c2 = st.columns([2, 3])
    with c1:
        days = {"2 weeks": 14, "3 months": 91, "1 year": 365}[ui.choice("Window", ["2 weeks", "3 months", "1 year"],
                                                                        key="bb_ann_days", default="3 months")]
    with c2:
        only = st.toggle("S&P 500 members only", value=True, key="bb_ann_members")
    recent = ann[ann["tradable_at"] >= pd.Timestamp.now(tz="America/New_York") - pd.Timedelta(days=days)]
    if only:
        recent = recent[recent["member"]]
    if recent.empty:
        st.caption("None in this window.")
    else:
        ui.table(pd.DataFrame({
            "When (ET)": recent["tradable_at"].dt.strftime("%Y-%m-%d %H:%M"), "Ticker": recent["ticker"],
            "Company": recent["company"], "What": recent["kind"].map(KIND_LABEL), "Amount $bn": recent["amount_usd"] / 1e9,
            "% of cap": recent["pct_cap"] * 100, "Summary": recent["summary"], "Filing": recent["url"]}),
            hide_index=True, column_config={
                "Amount $bn": st.column_config.NumberColumn(format="%.2f"),
                "% of cap": st.column_config.NumberColumn(format="%.1f%%", help="Amount / today's market cap"),
                "Filing": st.column_config.LinkColumn(display_text="8-K")})
    cs = news("classify_summary", "json") or {}
    st.caption(f"From 8-Ks (cover and press releases) collected by SentIQ as they are filed; each candidate filing "
               f"is read once by {cs.get('model', 'Claude')}, which keeps first disclosures of a new, larger or "
               f"replacement authorization, an accelerated repurchase or a tender offer, and drops recaps of programs "
               f"announced earlier. 'When' is when the market could first act on it. Classified so far: "
               f"{cs.get('classified', 0):,} filings, ~${cs.get('spent_usd', 0):,.2f}.")
    at = cfg.ANNOUNCE_TEST
    with st.expander("Do announcements move the stock? (tested)"):
        st.markdown(
            f"**At the announcement, yes; afterwards, no.** {at['events']:,} announcements found this way "
            f"({at['period']}), returns over SPY. From the last close before the filing to the first close after "
            f"it the stock gained **{at['react']:+.2f}%** on average (t {at['react_t']:.1f}); "
            f"{at['react_alone']:+.2f}% when the 8-K carried only the buyback (t {at['react_alone_t']:.1f}). "
            f"Inside earnings releases it beat other earnings releases of buyback-active companies that only "
            f"recapped an existing program, in the same weeks, by {at['react_vs_control']:+.2f}% "
            f"(t {at['react_vs_control_t']:.1f}, {at['weeks']} weeks).\n\n"
            f"After that first close nothing is left: next 5 days about {at['d5']:+.1f}%, next 20 "
            f"{at['d20']:+.2f}% (t {at['d20_t']:.1f}), next 60 {at['d60']:+.2f}% (t {at['d60_t']:.1f}; vs the "
            f"control {at['d60_vs_control']:+.2f}%, t {at['d60_vs_control_t']:.1f}). The older finding of a "
            f"multi-year drift after buyback announcements does not show here. No run-up before either "
            f"({at['pre21_lo']:+.2f}% to {at['pre21_hi']:+.2f}% over the prior 21 days, not significant).\n\n"
            f"Filed outside market hours, part of the move is still there at the next open: the gap averaged "
            f"{at['gap_alone']:+.2f}% (buyback-only 8-Ks) and {at['gap_earn']:+.2f}% (in earnings releases), then "
            f"open to close added **{at['oc_alone']:+.2f}%** (t {at['oc_alone_t']:.1f}, {at['oc_alone_n']:,} filings) "
            f"and {at['oc_earn']:+.2f}% (t {at['oc_earn_t']:.1f}, {at['oc_earn_n']:,}); recaps of existing programs "
            f"added about {at['oc_control']:.1f}%. That is before costs, and only rows on the page before the open "
            f"could use it.\n\n"
            f"Caveats: about {at['precision']:.0%} of flagged rows were real first disclosures in a hand check; "
            f"returns are against SPY, not size-matched; the open-to-close test covers S&P 500 and NYSE names only.")

# ================================================================= blackout share
st.subheader("Share of the S&P 500 in its buyback blackout (estimated)")
rng = ui.choice("Range", list(cfg.RANGES), key="bb_range", default="1Y")
days = cfg.RANGES[rng]
s = share.copy()
s["date"] = pd.to_datetime(s["date"])
if days:
    s = s[s["date"] >= as_of - pd.Timedelta(days=days)]
fig = go.Figure()
lines = [("share_cap", "By market cap", "cap", "solid"), ("share_count", "By number of companies", "count", "dash")]
for col, name, key, dash in lines:
    if col in s:
        fig.add_trace(go.Scatter(x=s["date"], y=s[col] * 100, mode="lines", name=name,
                                 line={"width": 2, "color": cfg.COLORS[key], "dash": dash},
                                 hovertemplate=f"{name}: %{{y:.0f}}%<extra></extra>"))
future = s[s["projected"]]
if len(future):
    fig.add_vrect(x0=future["date"].min(), x1=future["date"].max(), fillcolor=ui.PALETTE["grey"], opacity=0.12,
                  line_width=0, annotation_text="projected", annotation_position="top left")
fig.update_layout(height=320, margin={"l": 0, "r": 0, "t": 30, "b": 0}, hovermode="x unified",
                  yaxis={"range": [0, 100], "ticksuffix": "%"}, legend={"orientation": "h", "y": 1.12, "x": 0})
ui.chart(fig, key="bb_share")
st.caption(f"A window is assumed to shut {summary['shut_days_before_close']} days before a company's fiscal quarter "
           f"ends and reopen {summary['reopen_bdays']} trading days after its earnings release (past releases from 8-K "
           "filings, upcoming ones from the earnings calendar). Policies vary, and companies with a pre-arranged "
           "10b5-1 plan keep buying through blackouts. Cap weights are today's.")

# ================================================================= reopening soon
st.subheader("Windows reopening soon")
if soon.empty:
    st.info(f"No member is estimated to reopen in the next {cfg.REOPEN_SOON_BDAYS} trading days.")
else:
    v = soon.sort_values(["reopens", "mcap"], ascending=[True, False])
    ui.table(pd.DataFrame({
        "Symbol": v["symbol"], "Name": v["name"], "Sector": v["sector"].map(lambda x: SECTOR_SHORT.get(x, x)),
        "Earnings": pd.to_datetime(v["window_release"]).dt.date, "Date from": v["window_source"],
        "Reopens (est.)": pd.to_datetime(v["reopens"]).dt.date, "Bought, 12m $bn": v["repurchased_ttm"] / 1e9,
        "Buyback yield": v["buyback_yield"] * 100, "Auth left, % cap": v["remaining_pct_cap"] * 100}),
        hide_index=True, column_config={
            "Bought, 12m $bn": st.column_config.NumberColumn(format="%.1f"),
            "Buyback yield": st.column_config.NumberColumn(format="%.1f%%"),
            "Auth left, % cap": st.column_config.NumberColumn(format="%.1f%%")})

# ================================================================= all members
st.subheader("Members")
c1, c2 = st.columns([3, 2])
with c1:
    sectors = sorted(stocks["sector"].dropna().unique())
    pick = st.selectbox("Sector", ["All sectors", *sectors], key="bb_sector")
with c2:
    status = ui.choice("Status", ["All", "Window open", "Blackout"], key="bb_status")
v = stocks if pick == "All sectors" else stocks[stocks["sector"] == pick]
if status != "All":
    v = v[v["blackout"].fillna(False).astype(bool) == (status == "Blackout")]
v = v.sort_values("buyback_yield", ascending=False, na_position="last")
shut = v["blackout"].fillna(False).astype(bool)
last_ann = {}
if ann is not None and not ann.empty:
    yr = ann[ann["tradable_at"] >= pd.Timestamp.now(tz="America/New_York") - pd.Timedelta(days=365)]
    for r in yr.sort_values("tradable_at").itertuples():
        amt = f" ${r.amount_usd / 1e9:,.1f}bn" if pd.notna(r.amount_usd) else ""
        last_ann[r.ticker] = f"{r.tradable_at:%Y-%m-%d} {KIND_LABEL.get(r.kind, r.kind)}{amt}"
window = [f"shut, reopens {pd.Timestamp(r):%b %d}" if b and pd.notna(r) else
          (f"open, shuts {pd.Timestamp(n):%b %d}" if pd.notna(n) else "open")
          for b, r, n in zip(shut, v["reopens"], v["next_shut"])]
table = pd.DataFrame({
    "Symbol": v["symbol"], "Name": v["name"], "Sector": v["sector"].map(lambda x: SECTOR_SHORT.get(x, x)),
    "Cap $bn": v["mcap"] / 1e9, "Bought, 12m $bn": v["repurchased_ttm"] / 1e9, "Buyback yield": v["buyback_yield"] * 100,
    "Share count, 1y": v["share_change_1y"] * 100, "Auth left $bn": v["remaining_auth"] / 1e9,
    "Auth left, % cap": v["remaining_pct_cap"] * 100,
    "Announced (12m)": v["symbol"].map(last_ann), "Window (est.)": window,
    "Next earnings": pd.to_datetime(v["next_release"]).dt.date})
num = st.column_config.NumberColumn
ui.table(table, hide_index=True, height=520, column_config={
    "Cap $bn": num(format="%,.0f"), "Bought, 12m $bn": num(format="%.1f"),
    "Buyback yield": num(format="%.1f%%", help="Last four reported quarters of buybacks / today's market cap"),
    "Share count, 1y": num(format="%+.1f%%", help="Change in the diluted share count over a year, split-adjusted: "
                                                   "buybacks net of new shares issued"),
    "Auth left $bn": num(format="%.1f"), "Auth left, % cap": num(format="%.1f%%"),
    "Announced (12m)": st.column_config.TextColumn(help="Latest buyback announcement in the last year, from its 8-K")})
st.caption(f"{len(v)} members. Buyback figures older than ~6 months are blanked (no recent filing).")

# ================================================================= what it's worth
t = cfg.TEST
with st.expander("What is known when, and does the blackout matter?"):
    st.markdown(
        "- **Announced:** a repurchase *authorization* (a ceiling, often with no end date). It isn't a commitment; "
        "many programs are never used in full. Accelerated repurchases with a bank and tender offers are announced "
        "too, but most buying is open-market.\n"
        "- **Reported afterwards:** the dollars spent each quarter (cash-flow statement) and the shares bought per "
        "month with the authorization left (10-Q / 10-K). A 2023 SEC rule requiring daily detail was struck down "
        "in court the same year, so nothing finer exists.\n"
        "- **Never disclosed:** blackout windows. The estimate here (shut two weeks before the quarter ends, reopen "
        "two trading days after earnings) matches common company policy; any one company may differ.\n"
        f"- **Tested ({t['period']}, S&P 500 members at the time):** the idea that the market is weaker while most "
        f"companies are in blackout did not hold: the share in blackout and the S&P 500's next 20 days had a rank "
        f"correlation of {t['market_rank_corr']:+.2f} (t {t['market_t']:.1f}, {t['market_periods']} periods), the "
        f"opposite sign and not reliable; next-day returns didn't differ (t {t['nextday_t']:.1f}). Heavy buyers "
        f"(buyback yield above about {t['heavy_cut']:.0%}) did {t['did_bp']:+.1f} bp a day better while their window "
        f"was open than while shut, compared with other companies (t {t['did_t']:.1f}, {t['did_months']} months), "
        f"which is the direction the buyback-support story predicts, but small, not reliable, and shrinking "
        f"({t['did_first']:+.1f} in 2010–17, {t['did_second']:+.1f} in 2018–26). Read this page as a calendar, "
        "not a signal.")
