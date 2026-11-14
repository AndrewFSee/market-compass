"""Pure calculations for the credit page (no I/O)."""
from __future__ import annotations

import pandas as pd


def tier_gaps(tiers: pd.DataFrame, days: int = 28) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp]:
    """Spread gaps between every pair of rating tiers, now and their change over `days` calendar days.

    `tiers`: OAS in bps by date, columns ordered best to worst rating (AAA ... CCC). Returns (gap, change, base date):
    square frames with rows = the riskier tier and columns = the safer one, filled below the diagonal only
    (gap.loc["CCC", "B"] = CCC - B). The change compares with the last date on or before `days` days ago.
    """
    t = tiers.dropna(how="all").ffill()
    cols = list(t.columns)
    now = t.iloc[-1]
    base_date = t.index[t.index <= t.index[-1] - pd.Timedelta(days=days)].max()
    then = t.loc[base_date]
    gap = pd.DataFrame(index=cols, columns=cols, dtype=float)
    change = gap.copy()
    for i, risky in enumerate(cols):
        for safe in cols[:i]:
            gap.loc[risky, safe] = now[risky] - now[safe]
            change.loc[risky, safe] = gap.loc[risky, safe] - (then[risky] - then[safe])
    return gap, change, base_date
