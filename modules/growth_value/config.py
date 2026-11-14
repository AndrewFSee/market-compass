"""Growth vs value timing: Ken French's large growth / large value portfolios (history, backtest) and a
live version of the same gaps from S&P 500 members' SEC filings (TickerLake's style job, `style/gaps`).
The "growth_value" job computes everything; the page only reads."""
from __future__ import annotations

MODULE = "growth_value"

FRENCH_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/6_Portfolios_2x3_CSV.zip"
GROWTH, VALUE = "BIG LoBM", "BIG HiBM"      # large caps, book / market below the 30th / above the 70th NYSE percentile
SECTIONS = {                                # unique piece of each section title in French's file
    "ret": "Average Value Weighted Returns -- Monthly",
    "bm": "BE_FYt-1/ME_June t",             # book (fiscal year t-1) / June-t market cap, VW, per month Jul t..Jun t+1
    "op": "Average of OP",                  # operating profitability, from 1963
    "inv": "investment",                    # asset growth log(A t-1 / A t-2), from 1963
}

Z_MIN_MONTHS = 120          # a z-score needs 10 years of earlier readings (expanding mean / sd, past data only)
THRESHOLD = 0.0             # rule: hold value when the investment-gap z is above this, else growth
COST = 0.0010               # per switch (whole book)
LAGS = (0, 2, 4, 6)         # months between the reading and acting on it (French posts July data ~October)
REALISTIC_LAG = 4
PERIODS = [("1974", "1999"), ("2000", None), ("1974", None)]   # None = latest month
EXCLUDE_BUBBLE = (1998, 2001)   # annual test without the dot-com years (formation Julys)
ETF_PAIRS = [("VUG", "VTV", "2004-02"), ("MGK", "VTV", "2008-01")]
# The SEC-based gap (last four quarters) runs ahead of French's (fiscal year t-1, fixed each July). Measured
# 2026-11-14, correlation with French's gap k months later: 0.17 (k 0), 0.36 (6), 0.47 (9), 0.48 (12), 0.35 (15);
# growth side 0.69 at k 12, value side only 0.19. So it is calibrated against French's reading a year later and
# shown as an early estimate of it, not as the signal.
LIVE_LEAD_MONTHS = 12
LIVE_MIN_CORR = 0.5         # below this the page calls the estimate loose
LIVE_MIN_MONTHS = 36
TRIES = 45                  # roughly how many timing candidates were tried before this one (stated on the page)

LABELS = {"inv": "Investment gap", "op": "Profitability gap", "vs": "Value spread"}
COLORS = {"growth": "#5B8DEF", "value": "#2BB5A6", "rule": "#2BB5A6", "late": "#F2C14E", "live": "#E4572E"}
