"""Credit module: data is published by credit-spread-analyzer's scripts/publish_to_hub.py
(registered as the "credit" job in registry.py). This page only reads it."""
from __future__ import annotations

MODULE = "credit"

# The project's own app (registry.LINKS; the page links to it through the hub's launcher)
FULL_APP_URL = "http://localhost:8502"

SPREAD_LABELS = {
    "hy_spread": "High yield (ICE OAS)",
    "baa_spread": "Moody's Baa − 10Y",
    "bbb_spread": "BBB (ICE OAS)",
    "ig_spread": "Investment grade (ICE OAS)",
    "aaa_spread": "Moody's Aaa − 10Y",
}

# The HMM's states, calmest first (publish_to_hub.py writes regime_prob_0..2), and the
# spread it is fitted on, drawn under the regime chart.
REGIME_STATES = {
    "regime_prob_0": ("Calm", "teal"),
    "regime_prob_1": ("Elevated", "amber"),
    "regime_prob_2": ("Stressed", "red"),
}
REGIME_SPREAD = "baa_spread"

# P(stress regime) bands for the badge: calm / elevated / stressed
STRESS_CUTS = [0.2, 0.5]
STRESS_LABELS = ["CALM", "ELEVATED", "STRESSED"]
STRESS_COLORS = ["teal", "amber", "red"]

# a tier counts as "widening" when it moved more than this over 20 trading days (bps)
WIDENING_BP = 10

HISTORY_SPANS = {"1Y": 1, "3Y": 3, "10Y": 10, "All": None}
GAP_CHANGE_DAYS = 28  # rating-gap matrix: change over 4 weeks
