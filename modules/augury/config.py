"""Risk-forecast module: data is published by augury's scripts/publish_to_hub.py
(registered as the "augury" job in registry.py). This page only reads it."""
from __future__ import annotations

MODULE = "augury"

# The project's own app (registry.LINKS; the page links to it through the hub's launcher)
FULL_APP_URL = "http://localhost:8506"

# the nightly refresh runs every weekday; warn once the forecasts are older than this
STALE_BUSINESS_DAYS = 1

# track-record chart windows, in trading days (None = everything since the track start)
TRACK_WINDOWS = {"1y": 252, "3y": 756, "All": None}
