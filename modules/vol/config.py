"""Vol module: data is published by stochastic-vol-surface's scripts/publish_to_hub.py
(registered as the "vol" job in registry.py). This page only reads it."""
from __future__ import annotations

MODULE = "vol"

# The project's own dashboard: `streamlit run src/dashboard/app.py --server.port 8504`
FULL_APP_URL = "http://localhost:8504"

GROUPS = {
    "Index & sector ETFs": ["SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK", "XLV", "XLI", "XLU", "SMH", "KRE", "XBI"],
    "Rates & credit": ["TLT", "IEF", "HYG", "LQD"],
    "International": ["EEM", "EFA", "EWZ"],
    "Commodities & crypto": ["GLD", "SLV", "USO", "UNG", "GDX", "IBIT", "VXX"],
    "Single stocks": ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "AVGO", "AMD", "TSLA", "NFLX", "JPM", "BAC",
                      "COIN", "PLTR"],
}

MARKET_VOLS = {
    "mkt_vix": "VIX", "mkt_vix9d": "VIX 9-day", "mkt_vix3m": "VIX 3-month",
    "mkt_vvix": "VVIX", "mkt_move": "MOVE (rates)", "mkt_ovx": "OVX (oil)",
}

# the scrapers run every weekday (DailyScraper at 4:30 PM); flag the data once it misses
# more than this many sessions. A session counts as due from SCRAPE_DONE_HOUR local time.
STALE_BUSINESS_DAYS = 0
SCRAPE_DONE_HOUR = 17
