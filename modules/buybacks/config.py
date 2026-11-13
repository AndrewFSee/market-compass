"""Buybacks module: repurchases from SEC filings and estimated blackout windows, published by
TickerLake's scripts/publish_buybacks_to_hub.py (the "buybacks" job in registry.py). This page only reads it."""
from __future__ import annotations

MODULE = "buybacks"
REOPEN_SOON_BDAYS = 10
RANGES = {"1Y": 365, "3Y": 3 * 365, "All": None}
COLORS = {"cap": "#2BB5A6", "count": "#5B8DEF"}   # count is also dashed

# Measured 2026-11-13 (scratch script buyback_test.py; release dates from 8-K Item 2.02 for 630 companies,
# 97% matched; S&P 500 members 2010-01..2026-10). The page states these; rerun the test if the window
# rules (TickerLake buybacks.SHUT_DAYS_BEFORE_CLOSE / REOPEN_BDAYS) change.
TEST = {
    "period": "2010–2026",
    "market_rank_corr": 0.118, "market_t": 1.5, "market_periods": 213,
    "nextday_hi_bp": 5.8, "nextday_lo_bp": 3.2, "nextday_t": 0.6,
    "heavy_cut": 0.052, "did_bp": 2.75, "did_t": 1.2, "did_months": 202, "did_first": 5.31, "did_second": 1.28,
}

# Announcement event study (2026-11-13, scratch script; 8-Ks 2019-01..2026-11 classified by the job, returns
# minus SPY on adjusted closes; day 0 = first close after the filing could be traded; t clusters by week).
# Control = earnings 8-Ks of companies only mentioning an existing program, same weeks.
ANNOUNCE_TEST = {
    "period": "2019–2026", "events": 1786, "control": 9375,
    "react": 1.30, "react_t": 7.5, "react_alone": 1.33, "react_alone_t": 9.4,
    "react_vs_control": 1.52, "react_vs_control_t": 4.2, "weeks": 241,
    "d5": 0.1, "d20": -0.04, "d20_t": 0.2, "d60": -0.05, "d60_t": -1.2,
    "d60_vs_control": -0.89, "d60_vs_control_t": -1.1, "pre21_lo": -0.74, "pre21_hi": 0.63,
    "precision": 0.92,
    # filings outside the session (S&P + NYSE names with opens): gap = close -1 -> open 0, then open 0 -> close 0
    "gap_alone": 0.92, "oc_alone": 0.41, "oc_alone_t": 4.5, "oc_alone_n": 583,
    "gap_earn": 0.75, "oc_earn": 0.57, "oc_earn_t": 2.6, "oc_earn_n": 1015, "oc_control": 0.0,
}
