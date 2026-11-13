"""Style module: value and growth scores of S&P 500 members, published by TickerLake's
scripts/publish_style_to_hub.py (the "style" job in registry.py). This page only reads it."""
from __future__ import annotations

MODULE = "style"

# raw factor columns -> label, multiplier for display, unit
FACTORS = {
    "bp": ("Book / price", 1, ""),
    "ep": ("Earnings / price", 100, "%"),
    "sp": ("Sales / price", 1, ""),
    "dp": ("Dividend yield", 100, "%"),
    "epsg3": ("EPS trend /yr", 100, "%"),
    "spsg3": ("Sales/share trend /yr", 100, "%"),
    "inv": ("Capex / assets", 100, "%"),
    "roa": ("Return on assets", 100, "%"),
}
QUADRANTS = ["cheap, growing", "cheap, slow", "pricey, growing", "pricey, slow"]
SECTOR_SHORT = {
    "Information Technology": "Tech", "Communication Services": "Comm", "Consumer Discretionary": "Discretionary",
    "Consumer Staples": "Staples", "Health Care": "Health", "Financials": "Financials", "Industrials": "Industrials",
    "Energy": "Energy", "Materials": "Materials", "Utilities": "Utilities", "Real Estate": "Real estate",
}
LABEL_ALL_UP_TO = 80     # stock map: label every selected stock up to this many
PATH_MONTHS = 6          # sector map: show where each sector was this many month-ends ago
COLORS = {"value": "#2BB5A6", "growth": "#5B8DEF"}   # growth is also dashed, so it never relies on hue
