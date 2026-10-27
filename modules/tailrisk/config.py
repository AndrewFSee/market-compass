"""Tail-risk module: data is published by tail-risk-scenario-engine's scripts/publish_to_hub.py
(registered as the "tailrisk" job in registry.py). This page only reads it."""
from __future__ import annotations

MODULE = "tailrisk"

# The project's own dashboard: `streamlit run app/streamlit_app.py --server.port 8505`
FULL_APP_URL = "http://localhost:8505"

HEDGE_LABELS = {"unhedged": "Unhedged"}  # others are labelled from their names, e.g. put_0.95m


def hedge_label(name: str) -> str:
    if name in HEDGE_LABELS:
        return HEDGE_LABELS[name]
    if name.startswith("put_"):
        return f"SPY put, {float(name[4:].rstrip('m')):.0%} strike"
    if name.startswith("inverse_etf_"):
        return f"Inverse SPY, {name.removeprefix('inverse_etf_')}"
    return name
