"""Credit module: data is published by credit-spread-analyzer's scripts/publish_to_hub.py
(registered as the "credit" job in registry.py). This page only reads it."""
from __future__ import annotations

MODULE = "credit"

# The project's own full dashboard (start it with `python scripts/run_dashboard.py
# --server.port 8502` in that folder); linked from the page and the sidebar.
FULL_APP_URL = "http://localhost:8502"

SPREAD_LABELS = {
    "hy_spread": "High yield (ICE OAS)",
    "baa_spread": "Moody's Baa − 10Y",
    "bbb_spread": "BBB (ICE OAS)",
    "ig_spread": "Investment grade (ICE OAS)",
    "aaa_spread": "Moody's Aaa − 10Y",
}

# P(stress regime) bands for the badge: calm / elevated / stressed
STRESS_CUTS = [0.2, 0.5]
STRESS_LABELS = ["CALM", "ELEVATED", "STRESSED"]
STRESS_COLORS = ["teal", "amber", "red"]

# a tier counts as "widening" when it moved more than this over 20 trading days (bps)
WIDENING_BP = 10

HISTORY_SPANS = {"1Y": 1, "3Y": 3, "10Y": 10, "All": None}
