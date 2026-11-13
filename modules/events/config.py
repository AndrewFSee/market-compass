"""Events module: release calendar and prediction-market odds, published by TickerLake's
scripts/publish_events_to_hub.py (the "events" job in registry.py). This page only reads it."""
from __future__ import annotations

MODULE = "events"

CALENDAR_DAYS = 21          # releases shown in the calendar table
IMPORTANCE_ICON = {"high": "🔴 High", "medium": "🟡 Medium", "low": "⚪ Low"}
FED_COLORS = {"cut": "teal", "hold": "amber", "hike": "red"}

# Short names for the calendar's "Markets say" column (Polymarket titles are trimmed instead)
SERIES_LABEL = {
    "KXCPI": "CPI m/m", "KXCPICORE": "Core CPI m/m", "KXPAYROLLS": "Payrolls", "KXU3": "Unemployment",
    "KXJOBLESSCLAIMS": "Claims", "KXPCECORE": "Core PCE m/m", "KXUSPPI": "PPI m/m", "KXUSRETAIL": "Retail sales m/m",
    "KXGDP": "GDP", "KXISMPMI": "ISM PMI", "KXFEDDECISION": "Fed",
}
