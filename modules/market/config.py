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


# ---------------------------------------------------------------- rotation map
# Where each ETF sits in its strength cycle against the benchmark, on weekly closes:
#   trend    = log(ETF / SPY) minus its ROTATION_TREND_WEEKS average, in standard deviations
#              of that gap over the last ROTATION_Z_WEEKS (right of centre = stronger than usual)
#   momentum = change in the trend reading over ROTATION_MOMENTUM_WEEKS (up = improving)
# 26/4 was picked from the candidates below on real data (2000-2026): none forecast
# reliably, and it gave the cleanest clockwise rotation without 10-week zig-zag.
ROTATION_GROUPS = {
    "Sectors": SECTORS,
    "Style": {t: f"{size} {style}" for size, row in STYLE_GRID.items() for style, t in row.items()},
    "Factors": FACTORS,
}
ROTATION_PERIOD = "max"  # full history, for the "does it predict?" statistics
ROTATION_TREND_WEEKS = 26
ROTATION_MOMENTUM_WEEKS = 4
ROTATION_Z_WEEKS = 52
ROTATION_TAIL_WEEKS = 26  # longest tail the page can show
# Overbought / oversold: RSI of the weekly ETF/SPY ratio. In sectors, readings >= 70 were
# followed by 0.4-1.0% underperformance vs the other sectors over 4 weeks, in both halves
# of the history; oversold bounces were weaker.
ROTATION_RSI_WEEKS = 14
ROTATION_RSI_CUTS = (30, 70)
# Statistics: next ROTATION_HORIZON weeks, relative to the group's average; non-overlapping
# dates; reported before and after ROTATION_SPLIT to show whether a result holds up.
ROTATION_HORIZON = 4
ROTATION_SPLIT = "2015-01-01"
ROTATION_CANDIDATES = {  # kind: trend | trend_change | return | rsi
    "Trend, 10 weeks": {"kind": "trend", "weeks": 10},
    "Trend, 26 weeks (map, across)": {"kind": "trend", "weeks": 26},
    "Trend, 52 weeks": {"kind": "trend", "weeks": 52},
    "4-wk change of 26-wk trend (map, up)": {"kind": "trend_change", "weeks": 26, "change": 4},
    "Relative return, 4 weeks": {"kind": "return", "weeks": 4},
    "Relative return, 13 weeks": {"kind": "return", "weeks": 13},
    "Relative return, 12 months ex last month": {"kind": "return", "weeks": 52, "skip": 4},
    "Relative RSI, 14 weeks": {"kind": "rsi", "weeks": 14},
}


# ---------------------------------------------------------------- sector internals
# S&P 500 members (GICS sector from Wikipedia) behind each sector ETF.
GICS_TO_ETF = {
    "Information Technology": "XLK", "Health Care": "XLV", "Financials": "XLF",
    "Consumer Discretionary": "XLY", "Consumer Staples": "XLP", "Energy": "XLE", "Industrials": "XLI",
    "Materials": "XLB", "Utilities": "XLU", "Real Estate": "XLRE", "Communication Services": "XLC",
}
INTERNALS_WINDOW = 20  # trading days (~4 weeks) for "beating SPY" and the EW - CW spread
INTERNALS_BROAD = 50   # % of members beating SPY that counts as broad participation
CONTRIBUTION_WINDOWS = {"1 wk": 5, "4 wk": 20, "13 wk": 63}  # drill-down periods, trading days
INTERNALS_HISTORY_DAYS = 252  # participation history kept for the page

# ---------------------------------------------------------------- fund flows
# Daily NAV and shares outstanding from State Street's free NAV-history file for each SPDR
# fund (since ~1998). Flow = change in shares x NAV. A file for date D is published the next
# morning, so signals use flows through the day before.
SSGA_NAV_URL = ("https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/"
                "navhist-us-en-{}.xlsx")
FLOW_TICKERS = list(SECTORS)  # all Select Sector SPDRs
FLOW_WINDOWS = {"1 wk": 5, "4 wk": 20, "13 wk": 63}  # trading days
FLOW_HISTORY_DAYS = 252

# ---------------------------------------------------------------- leadership & cross-asset
LEADERSHIP_WEEKS = 52  # heatmap length
DISPERSION_DAYS = 63   # trailing window for average pairwise correlation of sector returns
# Driver checks: does each sector's relative strength move with what should drive it?
#   driver: a Yahoo ticker, a FRED series id, or "a/b" for a ratio of two Yahoo tickers
#   sign: +1 if the sector should outperform when the driver rises, -1 if when it falls
CROSS_ASSET = [
    {"sector": "XLF", "driver": "T10Y3M", "label": "Yield curve (10Y - 3M)", "sign": 1, "kind": "fred",
     "why": "banks lend long and borrow short"},
    {"sector": "XLE", "driver": "CL=F", "label": "Crude oil", "sign": 1, "kind": "yahoo",
     "why": "energy earnings follow oil"},
    {"sector": "XLB", "driver": "HG=F/GC=F", "label": "Copper / gold", "sign": 1, "kind": "yahoo",
     "why": "industrial demand vs safety"},
    {"sector": "XLU", "driver": "DGS10", "label": "10Y Treasury yield", "sign": -1, "kind": "fred",
     "why": "bond proxy: higher yields compete"},
    {"sector": "XLRE", "driver": "DGS10", "label": "10Y Treasury yield", "sign": -1, "kind": "fred",
     "why": "financing costs and cap rates"},
    {"sector": "OFFENSE", "driver": "BAMLH0A0HYM2", "label": "High-yield spread", "sign": -1, "kind": "fred",
     "why": "risk appetite: tighter spreads favour cyclicals"},
]
# Offense = cyclical sectors vs defensive ones, equal-weighted
OFFENSE = ["XLK", "XLY", "XLC", "XLI", "XLF", "XLB"]
DEFENSE = ["XLP", "XLU", "XLV"]
CROSS_ASSET_WEEKS = 13  # change measured over this many weeks
CROSS_ASSET_CORR_WEEKS = 52  # rolling correlation of weekly changes


def cross_asset_yahoo() -> list[str]:
    return list(dict.fromkeys(t for c in CROSS_ASSET if c["kind"] == "yahoo" for t in c["driver"].split("/")))


def rotation_tickers() -> list[str]:
    return list(dict.fromkeys([BENCHMARK, *(t for g in ROTATION_GROUPS.values() for t in g)]))


def all_etf_tickers() -> list[str]:
    tickers = [BENCHMARK, VIX, SAFE_HAVEN, *style_tickers(), *SECTORS, *FACTORS]
    return list(dict.fromkeys(tickers))  # de-duplicate, keep order


# ---------------------------------------------------------------- global markets
# Descriptive table of other markets (US-listed ETFs, so one session and one currency).
# (ticker, name, group, region); groups and regions are the page's filters.
GLOBAL_MARKETS = [
    ("SPY", "S&P 500", "Equities", "US"), ("RSP", "S&P 500 equal weight", "Equities", "US"),
    ("QQQ", "Nasdaq-100", "Equities", "US"), ("DIA", "Dow Jones 30", "Equities", "US"),
    ("IWM", "Russell 2000", "Equities", "US"), ("MDY", "S&P MidCap 400", "Equities", "US"),
    ("ACWI", "All-world", "Equities", "Global"), ("EFA", "Developed ex-US", "Equities", "Global"),
    ("EEM", "Emerging markets", "Equities", "Global"),
    ("VGK", "Europe", "Equities", "Europe"), ("EWU", "United Kingdom", "Equities", "Europe"),
    ("EWG", "Germany", "Equities", "Europe"), ("EWQ", "France", "Equities", "Europe"),
    ("EWL", "Switzerland", "Equities", "Europe"), ("EWI", "Italy", "Equities", "Europe"),
    ("EWP", "Spain", "Equities", "Europe"),
    ("EWJ", "Japan", "Equities", "Asia/Pacific"), ("MCHI", "China", "Equities", "Asia/Pacific"),
    ("FXI", "China large caps", "Equities", "Asia/Pacific"), ("EWH", "Hong Kong", "Equities", "Asia/Pacific"),
    ("EWT", "Taiwan", "Equities", "Asia/Pacific"), ("EWY", "South Korea", "Equities", "Asia/Pacific"),
    ("INDA", "India", "Equities", "Asia/Pacific"), ("EWA", "Australia", "Equities", "Asia/Pacific"),
    ("EWS", "Singapore", "Equities", "Asia/Pacific"),
    ("EWC", "Canada", "Equities", "Americas"), ("EWZ", "Brazil", "Equities", "Americas"),
    ("EWW", "Mexico", "Equities", "Americas"),
    ("BIL", "T-bills 1-3 mo", "Bonds", "US Treasuries"), ("SHY", "Treasuries 1-3 yr", "Bonds", "US Treasuries"),
    ("IEI", "Treasuries 3-7 yr", "Bonds", "US Treasuries"), ("IEF", "Treasuries 7-10 yr", "Bonds", "US Treasuries"),
    ("TLT", "Treasuries 20+ yr", "Bonds", "US Treasuries"), ("TIP", "TIPS", "Bonds", "US Treasuries"),
    ("AGG", "US aggregate", "Bonds", "US credit"), ("MBB", "Mortgage-backed", "Bonds", "US credit"),
    ("LQD", "IG corporates", "Bonds", "US credit"), ("HYG", "High-yield corporates", "Bonds", "US credit"),
    ("MUB", "Municipals", "Bonds", "US credit"),
    ("BNDX", "International (hedged)", "Bonds", "International"), ("EMB", "Emerging-market USD", "Bonds", "International"),
    ("DBC", "Broad commodities", "Commodities", "Broad"), ("GLD", "Gold", "Commodities", "Metals"),
    ("SLV", "Silver", "Commodities", "Metals"), ("CPER", "Copper", "Commodities", "Metals"),
    ("PPLT", "Platinum", "Commodities", "Metals"), ("USO", "WTI crude oil", "Commodities", "Energy"),
    ("BNO", "Brent crude oil", "Commodities", "Energy"), ("UNG", "Natural gas", "Commodities", "Energy"),
    ("DBA", "Agriculture", "Commodities", "Agriculture"), ("CORN", "Corn", "Commodities", "Agriculture"),
    ("WEAT", "Wheat", "Commodities", "Agriculture"),
    ("UUP", "US dollar index", "Currencies", "Currencies"), ("FXE", "Euro", "Currencies", "Currencies"),
    ("FXY", "Japanese yen", "Currencies", "Currencies"), ("FXB", "British pound", "Currencies", "Currencies"),
    ("IBIT", "Bitcoin", "Currencies", "Crypto"),
]
GLOBAL_PERIOD = "2y"        # enough for 1-year returns and a 200-day average a year back
GLOBAL_SPARK_WEEKS = 52     # weekly closes kept for the table's sparkline


def global_tickers() -> list[str]:
    return [t for t, *_ in GLOBAL_MARKETS]


# ---------------------------------------------------------------- headline economy
# Shown as tiles; not part of any gauge. kind: level (last value), yoy (% vs 12 months
# earlier), mom_diff (change vs prior month, payrolls in thousands), saar (quarterly growth,
# annualized), spread (a - b). "release" links to TickerLake's calendar for the next date.
# CPI uses the unadjusted index: BLS's published 12-month change is computed on it.
# up_is_good colours the change: True green when up, False green when down, None neutral.
HEADLINE_ECON = [
    {"key": "fed_funds", "label": "Fed funds target", "series": ["DFEDTARL", "DFEDTARU"], "kind": "range",
     "unit": "%", "release": "fomc", "up_is_good": None},
    {"key": "ten_year", "label": "10Y Treasury", "series": ["DGS10"], "kind": "level", "unit": "%", "up_is_good": None},
    {"key": "curve", "label": "10Y - 2Y spread", "series": ["DGS10", "DGS2"], "kind": "spread", "unit": "pts", "up_is_good": None},
    {"key": "unemployment", "label": "Unemployment", "series": ["UNRATE"], "kind": "level", "unit": "%",
     "release": "jobs", "up_is_good": False},
    {"key": "payrolls", "label": "Payrolls, monthly change", "series": ["PAYEMS"], "kind": "mom_diff", "unit": "k",
     "release": "jobs"},
    {"key": "cpi", "label": "CPI, y/y", "series": ["CPIAUCNS"], "kind": "yoy", "unit": "%", "release": "cpi",
     "up_is_good": False},
    {"key": "core_cpi", "label": "Core CPI, y/y", "series": ["CPILFENS"], "kind": "yoy", "unit": "%",
     "release": "cpi", "up_is_good": False},
    {"key": "core_pce", "label": "Core PCE, y/y", "series": ["PCEPILFE"], "kind": "yoy", "unit": "%",
     "release": "pce", "up_is_good": False},
    {"key": "gdp", "label": "Real GDP, q/q annualized", "series": ["GDPC1"], "kind": "saar", "unit": "%",
     "release": "gdp"},
]
HEADLINE_SPARK = 24         # observations kept per tile for its sparkline


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
    ids += [c["driver"] for c in CROSS_ASSET if c["kind"] == "fred"]
    ids += [sid for h in HEADLINE_ECON for sid in h["series"]]
    return list(dict.fromkeys(ids))


# ---------------------------------------------------------------- gauges
# colors are listed low -> high band
GAUGES = {
    "fear_greed": {
        "title": "Fear / Greed",
        "lo": 0, "hi": 100, "cuts": [40, 60], "colors": ["red", "amber", "teal"],  # fear = red, as elsewhere
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
