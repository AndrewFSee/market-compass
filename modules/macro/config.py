"""Macro module: data is published by macro-regime-nowcaster's scripts/publish_to_hub.py
(registered as the "macro" job in registry.py). This page only reads it."""
from __future__ import annotations

MODULE = "macro"

# The project's own dashboard: `streamlit run src/dashboard/app.py --server.port 8503`
FULL_APP_URL = "http://localhost:8503"

# P(recession) bands for the badge
RECESSION_CUTS = [0.15, 0.40]
RECESSION_LABELS = ["LOW", "ELEVATED", "HIGH"]
RECESSION_COLORS = ["teal", "amber", "red"]

SIGNAL_LABELS = {
    "cfnai": "Chicago Fed activity index (CFNAI)",
    "probit": "Probit: yield curve, credit, factors",
    "sahm": "Sahm rule (unemployment)",
    "rsm": "Markov-switching model",
}

FACTOR_LABELS = {
    "real_activity": "Real activity",
    "credit_premium": "Credit premium",
    "financial_stress": "Financial stress",
    "yield_curve": "Yield curve",
    "long_rates": "Long rates",
}

# NBER recessions since the walk-forward panel starts (for chart shading)
NBER_RECESSIONS = [
    ("1969-12-01", "1970-11-30"), ("1973-11-01", "1975-03-31"), ("1980-01-01", "1980-07-31"),
    ("1981-07-01", "1982-11-30"), ("1990-07-01", "1991-03-31"), ("2001-03-01", "2001-11-30"),
    ("2007-12-01", "2009-06-30"), ("2020-02-01", "2020-04-30"),
]

HISTORY_SPANS = {"10Y": 10, "25Y": 25, "All": None}
PANEL_STALE_DAYS = 45  # the panel is monthly; flag it once it misses a month
