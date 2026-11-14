"""Synthetic inputs for --demo and the tests: a French-format 6-portfolio file and ETF closes."""
from __future__ import annotations

import numpy as np
import pandas as pd

COLS = ["SMALL LoBM", "ME1 BM2", "SMALL HiBM", "BIG LoBM", "ME2 BM2", "BIG HiBM"]


def _table(title: str, idx: pd.DatetimeIndex, values: np.ndarray, fmt: str = "%Y%m") -> str:
    lines = [f"  {title}", "," + ",".join(COLS)]
    for d, row in zip(idx, values):
        lines.append(d.strftime(fmt) + "," + ",".join(f"{v:9.4f}" for v in row))
    return "\n".join(lines) + "\n\n\n"


def french_text(seed: int = 11, end: str = "2026-09-30") -> str:
    """Monthly returns from 1926-07, book / June ME for each formation year, OP and investment from
    1963-07. The investment gap (growth minus value) predicts value minus growth a little."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("1926-07-31", end, freq="ME")
    n = len(idx)
    form = np.where(idx.month >= 7, idx.year, idx.year - 1)
    years = np.unique(form)
    gap_y = pd.Series(0.05 + 0.04 * rng.standard_normal(len(years)), index=years)   # growth - value asset growth
    gap = gap_y.reindex(form).to_numpy()
    mkt = 0.008 + 0.05 * rng.standard_normal(n)
    vg = 0.002 + 0.25 * (gap - 0.05) + 0.03 * rng.standard_normal(n)              # value minus growth, monthly
    rets = np.column_stack([mkt + 0.01 * rng.standard_normal(n) for _ in range(6)])
    rets[:, 3] = mkt - vg / 2
    rets[:, 5] = mkt + vg / 2
    bm = np.column_stack([np.full(n, b) for b in (0.5, 1.0, 2.0, 0.45, 1.0, 1.6)]) * np.exp(0.1 * rng.standard_normal((n, 1)))
    inv = np.column_stack([np.full(n, x) for x in (0.12, 0.07, 0.03, 0.10, 0.06, 0.0)])
    inv[:, 5] = 0.04
    inv[:, 3] = 0.04 + gap
    op = np.column_stack([np.full(n, x) for x in (0.15, 0.2, 0.12, 0.3, 0.2, 0.15)]) + 0.01 * rng.standard_normal((n, 1))
    later = idx >= "1963-07-31"
    txt = ("This file was created by using the 202609 CRSP database.\nIt contains value-weighted returns (synthetic).\n\n\n"
           + _table("Average Value Weighted Returns -- Monthly", idx, rets * 100)
           + _table("Average Equal Weighted Returns -- Monthly", idx, rets * 100)
           + _table("For portfolios formed in June of year t\r  Value Weight Average of BE_FYt-1/ME_June t Calculated "
                    "for June of t to June of t+1", idx, bm)
           + _table("For portfolios formed in June of year t\r  Value Weight Average of OP Calculated as:", idx[later],
                    op[later])
           + _table("For portfolios formed in June of year t\r  Value Weight Average of investment (rate of growth of "
                    "assets)", idx[later], inv[later]))
    return txt


def etf_closes(seed: int = 12) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2004-01-26", "2026-11-13")
    r = 0.0003 + 0.011 * rng.standard_normal((len(idx), 3))
    return pd.DataFrame(100 * np.exp(np.cumsum(r, axis=0)), index=idx, columns=["VUG", "VTV", "MGK"])
