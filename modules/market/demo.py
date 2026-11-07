"""Synthetic inputs with the same shape as the real data pulls, so the whole
pipeline and dashboard can be tried without any network access."""
from __future__ import annotations

import numpy as np
import pandas as pd

from modules.market import config as cfg

# id -> (frequency, starting level, step volatility, kind)
#   kind "pos": multiplicative random walk; "ar": mean-reverting around the level
_FRED_SHAPES = {
    "D": {"BAMLH0A0HYM2": (4.0, 0.03, "ar"), "BAMLC0A0CM": (1.3, 0.015, "ar"),
          "DGS2": (3.0, 0.04, "ar"), "DGS10": (4.2, 0.03, "ar"), "DFII10": (1.0, 0.03, "ar"),
          "RRPONTSYD": (300, 0.03, "pos"),
          "DTWEXBGS": (115, 0.003, "pos"), "T10Y3M": (0.8, 0.03, "ar"), "BAA10Y": (2.2, 0.02, "ar")},
    "W": {"WALCL": (7.0e6, 0.004, "pos"), "WTREGEN": (7.5e5, 0.04, "pos"), "WRESBAL": (3200, 0.01, "pos"),
          "NFCI": (-0.4, 0.05, "ar"), "ICSA": (230e3, 0.03, "pos"), "CCSA": (1.8e6, 0.02, "pos")},
    "M": {"PERMIT": (1450, 0.03, "pos"), "HOUST": (1350, 0.04, "pos"), "AWHMAN": (40.5, 0.004, "pos"),
          "NEWORDER": (70e3, 0.012, "pos"), "ACOGNO": (40e3, 0.012, "pos"), "DGORDER": (280e3, 0.015, "pos"),
          "UMCSENT": (75, 0.05, "pos"), "M2REAL": (7e3, 0.004, "pos"), "TOTALSA": (16, 0.03, "pos"),
          "TEMPHELPS": (2800, 0.01, "pos"), "USALOLITOAASTSAM": (100, 0.003, "pos")},
    "Q": {"GDPC1": (20e3, 0.006, "pos")},
}
_FREQ = {"D": "B", "W": "W-WED", "M": "MS", "Q": "QS"}


def _walk(rng, n, level, vol, kind, drift=0.0):
    shocks = rng.normal(drift, vol, n)
    if kind == "pos":
        return level * np.exp(np.cumsum(shocks))
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = 0.985 * x[i - 1] + shocks[i]
    return level + x * max(abs(level), 1) * 3


def generate(seed: int = 7) -> dict:
    rng = np.random.default_rng(seed)
    end = pd.Timestamp.today().normalize()
    days = pd.bdate_range(end - pd.DateOffset(years=5), end)
    n = len(days)
    market = rng.normal(0.0004, 0.011, n)

    def asset(beta, idio, drift=0.0):
        return 100 * np.exp(np.cumsum(beta * market + rng.normal(drift, idio, n)))

    etf = {t: asset(rng.uniform(0.7, 1.3), 0.004) for t in cfg.all_etf_tickers()}
    etf[cfg.BENCHMARK] = asset(1.0, 0.0005)
    etf[cfg.SAFE_HAVEN] = asset(-0.15, 0.003)
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = 0.97 * x[i - 1] - 3 * market[i] + rng.normal(0, 0.03)
    etf[cfg.VIX] = 17 * np.exp(x)
    etf = pd.DataFrame(etf, index=days)

    rows, stocks = [], {}
    for sector, etf_ticker in cfg.GICS_TO_ETF.items():
        sector_factor = rng.normal(0, 0.006, n)
        for i in range(1, 9):
            sym = f"{etf_ticker}{i}"
            rows.append({"symbol": sym, "yf_symbol": sym, "name": f"Demo {sector} {i}", "sector": sector,
                         "sp500": True, "ndx": bool(rng.random() < 0.3)})
            stocks[sym] = 50 * np.exp(np.cumsum(rng.uniform(0.6, 1.4) * market + sector_factor
                                                + rng.normal(0, 0.012, n)))
    constituents = pd.DataFrame(rows)
    stocks = pd.DataFrame(stocks, index=days)
    caps = pd.Series(np.exp(rng.normal(25, 1.2, len(rows))), index=constituents["yf_symbol"], name="market_cap")

    fred = {}
    start = end - pd.DateOffset(years=36)
    for freq, specs in _FRED_SHAPES.items():
        idx = pd.date_range(start, end, freq=_FREQ[freq])
        if freq == "M":  # monthly data trickles in: the latest month is only partly reported
            idx = idx[:-1]
        for sid, (level, vol, kind) in specs.items():
            drift = 0.006 if sid == "GDPC1" else 0.0
            fred[sid] = pd.Series(_walk(rng, len(idx), level, vol, kind, drift), index=idx, name=sid)
    # leave a few late reporters out of the last month so the coverage logic is exercised
    for sid in ("NEWORDER", "ACOGNO", "DGORDER", "TOTALSA", "M2REAL"):
        fred[sid] = fred[sid].iloc[:-1]

    commodities = pd.DataFrame({t: asset(0.3, 0.02) for t in cfg.cross_asset_yahoo()}, index=days)
    rotation_prices = etf[cfg.rotation_tickers()].join(commodities)
    return {"fred": fred, "etf": etf, "rotation_prices": rotation_prices, "constituents": constituents,
            "stocks": stocks, "caps": caps, "missing": [], "demo": True}
