"""End-to-end regression anchors using author-published numbers.

Unit-level formula tests live in test_momentum.py. This module exercises the
full chain — daily closes → splits adjustment → monthly aggregation → monthly
returns → r(12-1) — and pins it to numbers the author published, so a future
refactor to any link in that chain trips the test.

Source of truth: the author's published VSMO worked example for 2022-03.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from adjustments.apply import adjust_dividend_amounts, apply_splits_to_prices
from config import DIVIDEND_TAX
from momentum.monthly import monthly_total_returns
from momentum.signals import r_skip_month
from storage.records import read_records
from storage.schemas import DIV_CASTS, PRICE_CASTS, SPLIT_CASTS

_REPO = Path(__file__).resolve().parent.parent
_DATA = _REPO / "data"

# 12 month-end closes for VSMO, 2021-03-31 .. 2022-02-25, from the author's
# published worked example. These survive forever — VSMO has been under
# sanctions since 2022, prices are frozen.
_VSMO_INFO_TXT_CLOSES: list[tuple[str, float]] = [
    ("2021-03-31", 26700.0),
    ("2021-04-30", 24140.0),
    ("2021-05-31", 27040.0),
    ("2021-06-30", 29300.0),
    ("2021-07-30", 30620.0),
    ("2021-08-31", 31220.0),
    ("2021-09-30", 34300.0),
    ("2021-10-29", 37380.0),
    ("2021-11-30", 44000.0),
    ("2021-12-30", 46900.0),
    ("2022-01-31", 47500.0),
    ("2022-02-25", 44000.0),
]


def _vsmo_prices_records() -> list[dict[str, Any]]:
    # Pipeline expects raw daily-price records — value is required, board not.
    return [
        {"date": d, "close": c, "value": 1.0, "board": "TQBR"} for d, c in _VSMO_INFO_TXT_CLOSES
    ]


def test_vsmo_2022_03_r12_e2e_matches_info_txt() -> None:
    """VSMO r(12-1) at t=2022-03 == 4.6458% ± 0.05% — end-to-end.

    Chain: prices list → apply_splits_to_prices → monthly_total_returns →
    r_skip_month. No splits, no dividends in window → adjusted == raw and
    total_return == price_return, so the geomean of monthly price returns
    must reproduce the author's 4.6458%.

    A break in monthly aggregation (e.g. not picking last trading day of month)
    or in r_skip_month indexing (off-by-one in the [t-11..t-1] window) will
    move this number by more than 0.05%.
    """
    prices_adj = apply_splits_to_prices(_vsmo_prices_records(), splits=[])
    monthly = monthly_total_returns(prices_adj, dividends_adj=[], tax=0.13, ticker="VSMO")

    # Panel matches what backtest engine feeds the signal: Period[M] index,
    # ticker columns, total_return values.
    panel = pd.DataFrame({"VSMO": monthly["total_return"]}, index=monthly.index)
    t = pd.Period("2022-03", freq="M")

    # r(12-1) needs 11 returns at t-11..t-1 = 2021-04..2022-02. monthly_total_returns
    # leaves a NaN for the first month (2021-03 has no prior close), so the 11
    # returns following it are exactly the window r_skip_month consumes.
    r12 = r_skip_month(panel, t, 12)["VSMO"]
    assert math.isclose(r12, 0.046458, abs_tol=0.0005), f"got {r12:.6f}, expected 0.046458"


def test_vsmo_monthly_aggregation_picks_last_trading_day() -> None:
    """Sanity guard: month-end close in monthly['close_adj'] must equal the
    last close of each calendar month, not e.g. the first or an average."""
    prices_adj = apply_splits_to_prices(_vsmo_prices_records(), splits=[])
    monthly = monthly_total_returns(prices_adj, dividends_adj=[], tax=0.13, ticker="VSMO")
    by_period = {str(p): float(v) for p, v in monthly["close_adj"].items()}
    for date_str, close in _VSMO_INFO_TXT_CLOSES:
        period = date_str[:7]
        assert math.isclose(by_period[period], close, rel_tol=1e-12), (
            f"{period}: pipeline produced {by_period[period]}, author's example has {close}"
        )


# Snapshot anchors — NOT externally verified (unlike VSMO). r(12-1) at a fixed
# settled date, computed once from committed raw via the production chain
# (read_records → splits/divs adjust → monthly → signal). They trip if a
# refactor moves any link in that chain. Both are blue chips with full history
# and no splits; LKOH has buybacks, SBER does not — different code paths.
# If a dividend backfill touches the 2023 window, recompute and update.
_SNAPSHOT_PERIOD = "2023-12"
_SNAPSHOT_R12: dict[str, float] = {
    "LKOH": 0.060941,
    "SBER": 0.072061,
}


def _committed_r12(ticker: str, period: str) -> float:
    prices = read_records(_DATA / "prices_iss" / f"{ticker}.csv", casts=PRICE_CASTS)
    splits = read_records(_DATA / "splits" / f"{ticker}.csv", casts=SPLIT_CASTS)
    dividends = read_records(_DATA / "dividends" / f"{ticker}.csv", casts=DIV_CASTS)
    prices_adj = apply_splits_to_prices(prices, splits)
    dividends_adj = adjust_dividend_amounts(dividends, splits, ticker=ticker)
    monthly = monthly_total_returns(prices_adj, dividends_adj, tax=DIVIDEND_TAX, ticker=ticker)
    panel = pd.DataFrame({ticker: monthly["total_return"]}, index=monthly.index)
    return float(r_skip_month(panel, pd.Period(period, freq="M"), 12)[ticker])


@pytest.mark.parametrize("ticker", sorted(_SNAPSHOT_R12))
def test_snapshot_r12_anchor(ticker: str) -> None:
    """r(12-1) for LKOH/SBER frozen against committed data — catches code drift."""
    got = _committed_r12(ticker, _SNAPSHOT_PERIOD)
    want = _SNAPSHOT_R12[ticker]
    assert math.isclose(got, want, abs_tol=0.0005), (
        f"{ticker} r(12-1) @ {_SNAPSHOT_PERIOD}: got {got:.6f}, snapshot {want:.6f}. "
        f"A refactor of the compute chain is a real regression; a change to "
        f"committed data in the 2023 window means recompute the snapshot."
    )
