"""Everything you are likely to want to tweak for the market module lives here:
tickers, FRED series, indicator recipes, gauge bands and labels."""
from __future__ import annotations

MODULE = "market"

# How much daily history to pull for ETFs and individual stocks.
PRICE_PERIOD = "5y"

TIMEFRAMES = ["1D", "5D", "20D", "QTD", "YTD", "1Y", "2Y"]

BENCHMARK = "SPY"
VIX = "^VIX"
SAFE_HAVEN = "IEF"  # bonds leg of the safe-haven component (7-10y Treasuries)

# ---------------------------------------------------------------- style grid
STYLE_GRID = {
    "Large": {"Value": "VTV", "Core": "IVV", "Growth": "IVW"},
    "Mid": {"Value": "MDYV", "Core": "MDY", "Growth": "MDYG"},
    "Small": {"Value": "VBR", "Core": "IJR", "Growth": "VBK"},
}

# ---------------------------------------------------------------- sectors
SECTORS = {
    "XLK": "Technology",
    "XLV": "Health Care",
    "XLF": "Financials",
    "XLY": "Consumer Disc.",
    "XLP": "Consumer Staples",
    "XLE": "Energy",
    "XLI": "Industrials",
    "XLB": "Materials",
    "XLU": "Utilities",
    "XLRE": "Real Estate",
    "XLC": "Communication",
}

# ---------------------------------------------------------------- factors
# 22 factor / market-segment ETFs. Swap freely - nothing else depends on this list.
FACTORS = {
    "MTUM": "Momentum",
    "QUAL": "Quality",
    "USMV": "Min Volatility",
    "VLUE": "Value Factor",
    "SIZE": "Size Factor",
    "RSP": "Equal Weight S&P",
    "SPHB": "High Beta",
    "SPLV": "Low Volatility",
    "VIG": "Dividend Growth",
    "VYM": "High Dividend",
    "SCHD": "Dividend Quality",
    "PKW": "Buybacks",
    "MOAT": "Wide Moat",
    "COWZ": "Free Cash Flow",
    "IWF": "Russell 1000 Growth",
    "IWD": "Russell 1000 Value",
    "IWM": "Russell 2000",
    "IWC": "Micro Cap",
    "QQQ": "Nasdaq 100",
    "DIA": "Dow 30",
    "EFA": "Developed ex-US",
    "EEM": "Emerging Markets",
}


def style_tickers() -> list[str]:
    return [t for row in STYLE_GRID.values() for t in row.values()]


def all_etf_tickers() -> list[str]:
    tickers = [BENCHMARK, VIX, SAFE_HAVEN, *style_tickers(), *SECTORS, *FACTORS]
    return list(dict.fromkeys(tickers))  # de-duplicate, keep order


# ---------------------------------------------------------------- FRED
# Credit spreads (ICE BofA option-adjusted spreads, percentage points).
HY_OAS = "BAMLH0A0HYM2"
IG_OAS = "BAMLC0A0CM"

# To use your own credit-spread project instead of FRED, have it publish a table
# into the hub data folder and point this at it, e.g.
#   CREDIT_OVERRIDE = {"module": "credit", "name": "spreads", "hy": "hy_oas", "ig": "ig_oas"}
# The table needs a date index and the two columns named here (in % points).
# credit-spread-analyzer publishes this with HY spliced back to 1996 (FRED alone: ~3 years).
# If the table is missing, the job falls back to FRED.
CREDIT_OVERRIDE: dict | None = {"module": "credit", "name": "spreads", "hy": "hy_oas", "ig": "ig_oas"}

# Liquidity Regime: 8 macro liquidity factors.
#   transform: level | diff63 (change over ~3 months) | pct63 (% change over ~3 months)
#   sign: +1 if a higher reading means looser liquidity, -1 if tighter
#   "NETLIQ" = Fed balance sheet - Treasury General Account - reverse repo
LIQUIDITY_FACTORS = [
    {"name": "High-yield credit spread", "series": HY_OAS, "transform": "level", "sign": -1},
    {"name": "Investment-grade credit spread", "series": IG_OAS, "transform": "level", "sign": -1},
    {"name": "2Y Treasury yield, 3-mo change", "series": "DGS2", "transform": "diff63", "sign": -1},
    {"name": "10Y real yield", "series": "DFII10", "transform": "level", "sign": -1},
    {"name": "Fed net liquidity, 3-mo % change", "series": "NETLIQ", "transform": "pct63", "sign": 1},
    {"name": "Bank reserves, 3-mo % change", "series": "WRESBAL", "transform": "pct63", "sign": 1},
    {"name": "Broad dollar, 3-mo % change", "series": "DTWEXBGS", "transform": "pct63", "sign": -1},
    {"name": "Financial conditions (Chicago Fed NFCI)", "series": "NFCI", "transform": "level", "sign": -1},
]
NETLIQ_PARTS = ["WALCL", "WTREGEN", "RRPONTSYD"]

# Economic Regime: leading indicators, each z-scored then weighted by how well it
# has lined up with real GDP growth 6 months later.
#   transform: pct6 (% change over 6 months) | diff6 (change over 6 months) | level
ECON_INDICATORS = [
    {"id": "ICSA", "name": "Initial jobless claims", "transform": "pct6", "sign": -1},
    {"id": "CCSA", "name": "Continuing claims", "transform": "pct6", "sign": -1},
    {"id": "PERMIT", "name": "Building permits", "transform": "pct6", "sign": 1},
    {"id": "HOUST", "name": "Housing starts", "transform": "pct6", "sign": 1},
    {"id": "AWHMAN", "name": "Avg weekly hours, manufacturing", "transform": "diff6", "sign": 1},
    {"id": "NEWORDER", "name": "Core capital goods orders", "transform": "pct6", "sign": 1},
    {"id": "ACOGNO", "name": "Consumer goods orders", "transform": "pct6", "sign": 1},
    {"id": "DGORDER", "name": "Durable goods orders", "transform": "pct6", "sign": 1},
    {"id": "UMCSENT", "name": "Consumer sentiment", "transform": "diff6", "sign": 1},
    {"id": "T10Y3M", "name": "Yield curve (10Y - 3M)", "transform": "level", "sign": 1},
    {"id": "BAA10Y", "name": "Baa corporate spread", "transform": "diff6", "sign": -1},
    {"id": "M2REAL", "name": "Real M2 money supply", "transform": "pct6", "sign": 1},
    {"id": "TOTALSA", "name": "Vehicle sales", "transform": "pct6", "sign": 1},
    {"id": "TEMPHELPS", "name": "Temporary help employment", "transform": "pct6", "sign": 1},
    {"id": "NFCI", "name": "Financial conditions (NFCI)", "transform": "level", "sign": -1},
    {"id": "USALOLITOAASTSAM", "name": "OECD leading indicator (US)", "transform": "diff6", "sign": 1},
]
GDP_SERIES = "GDPC1"
ECON_LEAD_MONTHS = 6
ECON_COVERAGE_THRESHOLD = 0.75  # share of indicators reported before a month counts as "final"


def all_fred_ids() -> list[str]:
    ids = [HY_OAS, IG_OAS, GDP_SERIES, *NETLIQ_PARTS]
    ids += [f["series"] for f in LIQUIDITY_FACTORS if f["series"] != "NETLIQ"]
    ids += [e["id"] for e in ECON_INDICATORS]
    return list(dict.fromkeys(ids))


# ---------------------------------------------------------------- gauges
# colors are listed low -> high band
GAUGES = {
    "fear_greed": {
        "title": "Fear / Greed",
        "lo": 0, "hi": 100, "cuts": [40, 60], "colors": ["teal", "amber", "red"],
        "caption": "Market sentiment, 0-100. Built from momentum, breadth, volatility, "
                   "safe-haven and junk-bond demand. Extremes tend to mark reversals.",
    },
    "liquidity": {
        "title": "Liquidity Regime",
        "lo": -100, "hi": 100, "cuts": [-35, 35], "colors": ["red", "amber", "teal"],
        "caption": "Composite of 8 macro liquidity factors (credit, rates, Fed balance "
                   "sheet, dollar). Higher = looser liquidity, lower = tighter.",
    },
    "technical": {
        "title": "Technical Regime",
        "lo": 0, "hi": 100, "cuts": [40, 60], "colors": ["red", "amber", "teal"],
        "caption": "S&P 500 technical composite (RSI, stochastic, MACD, distance from "
                   "50- and 200-day averages). Extremes = overbought / oversold.",
    },
    "economic": {
        "title": "Economic Regime",
        "lo": -100, "hi": 100, "cuts": [-35, 35], "colors": ["red", "amber", "teal"],
        "caption": "",  # filled in from the data (as-of month, coverage)
    },
}


# Trend readouts and the "vs S&P 500" statistics, in each gauge's own periods: trading
# days for the daily gauges, months for the economic gauge.
GAUGE_TREND = {
    "fear_greed": {"1 week": 5, "1 month": 21},
    "liquidity": {"1 week": 5, "1 month": 21},
    "technical": {"1 week": 5, "1 month": 21},
    "economic": {"1 month": 1, "3 months": 3},
}
GAUGE_HORIZON = {  # (periods, label) for "next period" market returns
    "fear_greed": (21, "1-month"), "liquidity": (21, "1-month"), "technical": (21, "1-month"),
    "economic": (3, "3-month"),
}
# How many periods after its date a reading could actually be known (publication delays:
# FRED daily series a day late, weekly ones like WALCL/NFCI up to a week, monthly data
# about a month). The "next period" statistics only use a reading from then on.
GAUGE_PUBLICATION_LAG = {"fear_greed": 1, "liquidity": 5, "technical": 0, "economic": 1}
# The benchmark is also pulled with its full history (since 1993) so the technical
# gauge and the vs-S&P statistics have decades to work with, not just PRICE_PERIOD.
BENCHMARK_LONG_PERIOD = "max"


def gauge_label(key: str, v: float | None) -> str:
    if v is None:
        return "NO DATA"
    if key == "fear_greed":
        return ("EXTREME FEAR" if v < 20 else "FEAR" if v < 40 else "NEUTRAL" if v <= 60
                else "GREED" if v <= 80 else "EXTREME GREED")
    if key == "technical":
        return ("OVERSOLD" if v < 20 else "BEARISH" if v < 40 else "NEUTRAL" if v <= 60
                else "BULLISH" if v <= 80 else "OVERBOUGHT")
    if key == "liquidity":
        return "TIGHT" if v < -35 else "NEUTRAL" if v <= 35 else "LOOSE"
    if key == "economic":
        return "CONTRACTING" if v < -35 else "MODERATE" if v <= 35 else "EXPANDING"
    return ""


# "Flat" band per timeframe (in %) for the performance tiles
FLAT_BAND = {"1D": 0.10, "5D": 0.30, "20D": 0.75, "QTD": 1.0, "YTD": 2.0, "1Y": 3.0, "2Y": 5.0}
