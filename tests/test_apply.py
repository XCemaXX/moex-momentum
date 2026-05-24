"""Tests for splits/dividends back-adjustment."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from adjustments.apply import (
    adjust_dividend_amounts,
    apply_splits_to_prices,
    cascade_for_dates,
)


def _prices(rows: list[tuple[str, float]]) -> list[dict[str, Any]]:
    return [{"date": d, "close": c, "value": 1.0} for d, c in rows]


def _split(date: str, before: int, after: int) -> dict[str, Any]:
    return {"date": date, "before": before, "after": after, "type": "x", "source": "test"}


def test_no_splits_adj_equals_raw() -> None:
    df = apply_splits_to_prices(_prices([("2024-01-08", 100.0), ("2024-01-09", 105.0)]), [])
    assert list(df["close_adj"]) == [100.0, 105.0]
    assert list(df["close_raw"]) == [100.0, 105.0]


def test_forward_split_scales_pre_dates_only() -> None:
    """Plan §8 invariant — forward 1:2 on D=index 2: closes before D get ×0.5,
    closes at/after D unchanged."""
    rows = _prices(
        [
            ("2024-01-08", 100.0),
            ("2024-01-09", 100.0),
            ("2024-01-10", 50.0),  # D — already post-split
            ("2024-01-11", 50.0),
            ("2024-01-12", 50.0),
        ]
    )
    df = apply_splits_to_prices(rows, [_split("2024-01-10", 1, 2)])
    assert list(df["close_adj"]) == [50.0, 50.0, 50.0, 50.0, 50.0]


def test_reverse_split_scales_pre_dates() -> None:
    """VTBR-like 5000:1 on D=index 2."""
    rows = _prices(
        [
            ("2024-07-11", 0.02),
            ("2024-07-12", 0.02),
            ("2024-07-15", 100.0),
            ("2024-07-16", 100.0),
        ]
    )
    df = apply_splits_to_prices(rows, [_split("2024-07-15", 5000, 1)])
    assert list(df["close_adj"]) == [100.0, 100.0, 100.0, 100.0]


def test_split_on_exact_date_is_post_scale() -> None:
    """Split D inclusive boundary: date == D is NOT scaled."""
    rows = _prices([("2024-01-09", 100.0), ("2024-01-10", 50.0)])
    df = apply_splits_to_prices(rows, [_split("2024-01-10", 1, 2)])
    assert df.loc[pd.Timestamp("2024-01-10"), "close_adj"] == 50.0


def test_cascade_of_two_splits() -> None:
    """Pre-1st split: coef = c1*c2. Between: coef = c2. After 2nd: coef = 1."""
    rows = _prices(
        [
            ("2024-01-01", 200.0),  # pre-both
            ("2024-06-01", 100.0),  # post-1st (forward 1:2), pre-2nd
            ("2024-12-01", 50.0),  # post-both (forward 1:2)
        ]
    )
    splits = [_split("2024-05-01", 1, 2), _split("2024-10-01", 1, 2)]
    df = apply_splits_to_prices(rows, splits)
    # cascade pre-1st = 0.5*0.5=0.25, between = 0.5, post-2nd = 1.
    assert list(df["close_adj"]) == [50.0, 50.0, 50.0]


def test_cascade_for_dates_basic() -> None:
    idx = pd.DatetimeIndex(["2024-04-30", "2024-05-01", "2024-05-02"])
    coef = cascade_for_dates(idx, [_split("2024-05-01", 1, 2)])
    assert list(coef) == [0.5, 1.0, 1.0]


def test_close_zero_rows_dropped() -> None:
    """close=0 pre-2010 ISS artefact: not in output."""
    rows = _prices([("2008-01-01", 0.0), ("2008-01-02", 100.0)])
    df = apply_splits_to_prices(rows, [])
    assert len(df) == 1
    assert pd.Timestamp("2008-01-02") in df.index


def test_empty_input_returns_empty_df() -> None:
    df = apply_splits_to_prices([], [_split("2024-01-01", 1, 2)])
    assert df.empty
    assert list(df.columns) == ["close_raw", "close_adj", "value"]


def test_invalid_split_raises() -> None:
    with pytest.raises(ValueError, match="positive"):
        apply_splits_to_prices(
            _prices([("2024-01-01", 100.0)]),
            [{"date": "2024-02-01", "before": 0, "after": 1, "type": "x", "source": "t"}],
        )


def test_dividend_adjust_invariance_when_before_split() -> None:
    """Dividend before split: amount and prices scale by the same factor →
    ratio amount/close_pre_ex is preserved."""
    splits = [_split("2024-05-01", 1, 2)]
    divs = [{"registry_close": "2024-04-15", "amount": 10.0, "currency": "RUB", "source": "t"}]
    out = adjust_dividend_amounts(divs, splits)
    assert out[0]["amount_adj"] == 5.0  # 10 * 0.5


def test_dividend_adjust_after_split_unchanged() -> None:
    splits = [_split("2024-05-01", 1, 2)]
    divs = [{"registry_close": "2024-06-15", "amount": 10.0, "currency": "RUB", "source": "t"}]
    out = adjust_dividend_amounts(divs, splits)
    assert out[0]["amount_adj"] == 10.0


def test_dividend_non_rub_dropped() -> None:
    divs = [
        {"registry_close": "2018-05-11", "amount": 0.3, "currency": "USD", "source": "moex_iss"},
        {"registry_close": "2018-05-11", "amount": 30.0, "currency": "RUB", "source": "moex_iss"},
    ]
    out = adjust_dividend_amounts(divs, [], ticker="POLY")
    assert len(out) == 1
    assert out[0]["currency"] == "RUB"


def test_dividend_adjust_empty() -> None:
    assert adjust_dividend_amounts([], []) == []
