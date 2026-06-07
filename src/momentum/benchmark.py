"""Benchmark index helpers shared by the backtest engine and the mages curve.

A data loader (like `universe.load_panel`), not part of the strategy engine — so
the mages package can reuse it without importing the backtest.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pandas as pd

from storage.records import read_records
from storage.schemas import INDEX_CASTS


def mcftrr_monthly_returns(indices_dir: Path) -> pd.Series:
    """MCFTRR last close of each month → monthly pct_change, indexed Period[M]."""
    rows = read_records(indices_dir / "MCFTRR.csv", casts=INDEX_CASTS)
    if not rows:
        return pd.Series(dtype=float)
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    period_idx = cast(pd.DatetimeIndex, df.index).to_period("M")
    last = df["close"].astype(float).groupby(period_idx).tail(1)
    s = pd.Series(last.values, index=pd.DatetimeIndex(last.index).to_period("M"), dtype=float)
    s.index.name = "month"
    return s.pct_change()
