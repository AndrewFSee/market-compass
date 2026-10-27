"""Look-alike (historical analog) engine: what tweak lives here."""
from __future__ import annotations

MODULE = "analogs"

# The market state used to find look-alikes. Each feature is z-scored on its own history
# and compared with today's; `weight` scales its say in the distance (0 = shown, not used).
# `lag` (trading days) is when the input could actually be known: credit and the yield
# curve come from FRED a day late, the liquidity gauge's weekly inputs up to a week late.
# The economic gauge is left out: its history uses revised data and full-sample weights.
FEATURES = {
    "trend":     {"label": "S&P 500 vs 200-day avg", "fmt": "{:+.1f}%", "weight": 1.0, "lag": 0},
    "momentum":  {"label": "S&P 500, last month", "fmt": "{:+.1f}%", "weight": 1.0, "lag": 0},
    "vix":       {"label": "VIX", "fmt": "{:.1f}", "weight": 1.0, "lag": 0},
    "vix_trend": {"label": "VIX vs its 50-day avg", "fmt": "{:+.0f}%", "weight": 1.0, "lag": 0},
    "hy":        {"label": "High-yield spread", "fmt": "{:.2f} pts", "weight": 1.0, "lag": 1},
    "hy_chg":    {"label": "High-yield spread, 3-month change", "fmt": "{:+.2f} pts", "weight": 1.0, "lag": 1},
    "liquidity": {"label": "Liquidity gauge", "fmt": "{:+.0f}", "weight": 1.0, "lag": 5},
    "curve":     {"label": "Yield curve, 10Y − 3M", "fmt": "{:+.2f} pts", "weight": 1.0, "lag": 1},
}

N_ANALOGS = 15           # distinct episodes to show
SEPARATION_DAYS = 63     # two look-alikes must be at least ~3 months apart
PATH_DAYS = 63           # how far the "what followed" paths run (trading days)
MIN_FEATURES = 6         # dates need at least this many features to be compared

# walk-forward check of the method: first test date and spacing (non-overlapping months)
EVAL_START_YEARS = 5     # need this much history before the first test
EVAL_STEP_DAYS = 21
