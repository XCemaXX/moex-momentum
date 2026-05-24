"""Eligibility universe for each rebalance month.

A ticker is eligible at month t iff:
    1. `type == "share"` in tickers.json
    2. Not delisted at t (`delisted_after > t-month-end`, or field absent)
    3. Has 13 consecutive monthly closes ending at t — i.e. non-NaN
       `total_return` for every month in [t-11, t]. The first monthly record's
       return is NaN by construction, so this implies 13 monthly closes.

The 13-window gives 12 returns: 11 for r(12-1) skip-month and r(6-1),
plus the current month t for σ(12) (locked plan §9).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import cast

import pandas as pd

from config import UNIVERSE_MIN_MONTHLY_CLOSES
from storage.records import read_records
from storage.schemas import MONTHLY_CASTS
from tickers import TickersDict

LOG = logging.getLogger(__name__)

_WINDOW = UNIVERSE_MIN_MONTHLY_CLOSES - 1  # 12 returns


def load_panel(
    monthly_dir: Path,
    ticker_filter: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load per-ticker monthly JSONL into wide panels.

    Returns (total_returns, close_adj, monthly_value_rub), each indexed by
    Period[M] with columns = ticker. Missing months become NaN.
    """
    files: list[Path]
    if ticker_filter is not None:
        files = [monthly_dir / f"{t}.csv" for t in ticker_filter]
        files = [p for p in files if p.exists()]
    else:
        files = sorted(monthly_dir.glob("*.csv"))

    returns_cols: dict[str, pd.Series] = {}
    close_cols: dict[str, pd.Series] = {}
    value_cols: dict[str, pd.Series] = {}
    for p in files:
        ticker = p.stem
        rows = read_records(p, casts=MONTHLY_CASTS)
        if not rows:
            continue
        idx = pd.PeriodIndex([r["month"] for r in rows], freq="M")
        returns_cols[ticker] = pd.Series([r["total_return"] for r in rows], index=idx, dtype=float)
        close_cols[ticker] = pd.Series([r["close_adj"] for r in rows], index=idx, dtype=float)
        value_cols[ticker] = pd.Series(
            [r.get("monthly_value_rub", 0.0) for r in rows], index=idx, dtype=float
        )
    if not returns_cols:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    returns_panel = pd.DataFrame(returns_cols).sort_index()
    close_panel = pd.DataFrame(close_cols).sort_index()
    value_panel = pd.DataFrame(value_cols).sort_index()
    return returns_panel, close_panel, value_panel


def _is_active(entry: dict[str, object], t_period: pd.Period) -> bool:
    """`delisted_after` is an ISO date. A ticker delisted on D is unavailable
    for any rebalance executed on or after the close of the month containing D.
    """
    da = entry.get("delisted_after")
    if not da:
        return True
    delisted_ts = pd.Timestamp(cast(str, da))
    return delisted_ts > t_period.to_timestamp(how="end")


def _share_active(tickers_dict: TickersDict, tk: str, t: pd.Period) -> bool:
    entry = tickers_dict.get(tk)
    if not entry or entry.get("type") != "share":
        return False
    return _is_active(cast(dict[str, object], entry), t)


def _trailing_value_medians(
    value_panel: pd.DataFrame,
    window_start: pd.Period,
    window_end: pd.Period,
    candidates: list[str],
) -> dict[str, float] | None:
    """Median monthly trading value over the window per candidate.

    Returns None if the value window is the wrong length (caller then skips the
    liquidity filter), else {ticker: median} for names with a non-NaN median.
    """
    v_mask = (value_panel.index >= window_start) & (value_panel.index <= window_end)
    v_window = value_panel.loc[v_mask]
    if len(v_window) != _WINDOW:
        return None
    cols = [c for c in candidates if c in v_window.columns]
    medians = v_window[cols].median(axis=0, skipna=True)
    return {str(tk): float(m) for tk, m in medians.items() if pd.notna(m)}


def universe_at(
    t: pd.Period,
    returns_panel: pd.DataFrame,
    tickers_dict: TickersDict,
    *,
    value_panel: pd.DataFrame | None = None,
    top_n: int | None = None,
) -> list[str]:
    """Sorted list of tickers eligible at month t (alphabetical, deterministic).

    Liquidity selection: if `top_n` is set, keep the N most liquid names by
    median(monthly_value_rub) over the 12-month window — a *relative* cut, stable
    name count across years and immune to ruble/market-scale drift.
    """
    if t not in returns_panel.index:
        return []
    window_end = t
    window_start = t - (_WINDOW - 1)
    if window_start not in returns_panel.index:
        return []
    mask = (returns_panel.index >= window_start) & (returns_panel.index <= window_end)
    window = returns_panel.loc[mask]
    if len(window) < _WINDOW:
        return []
    eligible = window.notna().all(axis=0)
    candidates = [
        str(tk) for tk, ok in eligible.items() if ok and _share_active(tickers_dict, str(tk), t)
    ]

    if top_n is not None and value_panel is not None and not value_panel.empty:
        medians = _trailing_value_medians(value_panel, window_start, window_end, candidates)
        if medians is not None:
            ranked = sorted(medians, key=lambda tk: (-medians[tk], tk))
            candidates = ranked[:top_n]
    return sorted(candidates)


def liquidity_cut(
    value_panel: pd.DataFrame, t: pd.Period, universe: list[str]
) -> tuple[str, float] | None:
    """Least-liquid name in `universe` and its trailing-window median value —
    the effective ₽ liquidity floor implied by the selection at month t."""
    window_start = t - (_WINDOW - 1)
    medians = _trailing_value_medians(value_panel, window_start, t, universe)
    if not medians:
        return None
    tk = min(medians, key=lambda k: medians[k])
    return tk, medians[tk]
