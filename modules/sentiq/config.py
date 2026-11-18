"""SentIQ module: scored 8-Ks and earnings calls, collector health and research status, published by
SentIQ's scripts/publish_news_to_hub.py (the "sentiq" job in registry.py). This page only reads it.

No returns are shown on purpose: SentIQ's holdout (from 2026-07-01) stays unseen until its
pre-registered looks (H3 stage 1 on/after 2027-05-31; H1, H2, H3 stage 2 on/after 2027-08-31)."""
from __future__ import annotations

MODULE = "sentiq"
ET = "America/New_York"

WINDOWS = {"1 day": 1, "1 week": 7, "1 month": 31, "3 months": 92}
GROUPS = ["S&P 500", "S&P 400", "S&P 600", "Nasdaq-100 extra"]   # "S&P 500 (outside membership)" off by default
EVENT_TYPES = ["earnings", "guidance", "m&a", "legal_regulatory", "product", "analyst_action", "macro", "other"]
EVENT_LABEL = {"earnings": "earnings", "guidance": "guidance", "m&a": "M&A", "legal_regulatory": "legal / regulatory",
               "product": "product", "analyst_action": "analyst action", "macro": "macro", "other": "other"}
RELEVANT = ["primary", "secondary"]          # the research samples use relevance >= secondary

FADES_HELP = ("Estimate, earnings / guidance 8-Ks and earnings calls only: the close two trading days after the "
              "first 15:50 decision at which the reading was usable. Before the holdout, the small drift linked "
              "to earnings-release sentiment showed up within about two sessions and was mostly gone after "
              "two to five. Unconfirmed until the H1 holdout test; no effect was found for other documents.")
MATERIALITY_HELP = ("The model's judgment of how much the document matters to the company's valuation (low / "
                    "medium / high). It says nothing about direction, but it does track how much the stock moved "
                    "(test 13, 2019 to mid-2026, market-adjusted move from the previous close through the first "
                    "close after the filing): earnings releases low / medium / high moved 1.7% / 2.2% / 4.2% on "
                    "average, other 8-Ks 1.4% / 1.8% / 3.1%. That move mostly happens before the reading is "
                    "usable, so it is a size-of-news label, not a trade signal.")
STALE_POLL_MINUTES = 15                     # last successful poll older than this (vs publish time) = warning
TOP_N = 15                                  # rows in each side of the earnings board
TONE_RANGES = {"1Y": 365, "3Y": 3 * 365, "All": None}
COLORS = {"pos": "#2BB5A6", "neg": "#E4572E", "line": "#5B8DEF", "bars": "#C9D1D9"}
