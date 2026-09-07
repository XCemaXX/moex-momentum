"""Tests for daily→monthly aggregation + total-return formula."""

from __future__ import annotations

import math
from datetime import date, timedelta

import pandas as pd

from adjustments.apply import (
    adjust_dividend_amounts,
    apply_splits_to_prices,
)
from momentum.monthly import monthly_total_returns, to_monthly_close


def _daily(start: str, n: int, closes: list[float]) -> pd.DataFrame:
    d0 = date.fromisoformat(start)
    idx = pd.DatetimeIndex([d0 + timedelta(days=i) for i in range(n)])
    return pd.DataFrame({"close_adj": closes}, index=idx)


def _records(start: str, n: int, close: float) -> list[dict[str, object]]:
    d0 = date.fromisoformat(start)
    return [
        {"date": (d0 + timedelta(days=i)).isoformat(), "close": close, "value": 1.0}
        for i in range(n)
    ]


def test_to_monthly_close_picks_last_trading_day() -> None:
    df = _daily("2024-01-29", 4, [100, 101, 102, 105])  # 29 Jan..1 Feb
    out = to_monthly_close(df)
    jan = pd.Period("2024-01", "M")
    feb = pd.Period("2024-02", "M")
    assert list(out.index) == [jan, feb]
    assert out.loc[jan, "close_adj"] == 102  # 2024-01-31
    assert out.loc[feb, "close_adj"] == 105  # 2024-02-01


def test_to_monthly_close_drops_in_progress_period() -> None:
    # April 30 + May 1-8 daily closes; as_of is mid-May → May is in progress, dropped.
    df = _daily("2026-04-30", 9, [100, 101, 102, 103, 104, 105, 106, 107, 108])
    out = to_monthly_close(df, as_of=pd.Timestamp("2026-05-08"))
    assert list(out.index) == [pd.Period("2026-04", "M")]


def test_to_monthly_close_keeps_completed_month_when_asof_in_next_month() -> None:
    # Same data; as_of in June → May has settled (last available close = 2026-05-08).
    df = _daily("2026-04-30", 9, [100, 101, 102, 103, 104, 105, 106, 107, 108])
    out = to_monthly_close(df, as_of=pd.Timestamp("2026-06-01"))
    assert list(out.index) == [pd.Period("2026-04", "M"), pd.Period("2026-05", "M")]


def test_to_monthly_close_excludes_current_day_within_period() -> None:
    # as_of == last trading day of the month, intra-day → still in-progress, dropped.
    # Rule is "as_of > period.end_time"; period.end_time is 23:59:59.
    df = _daily("2026-04-29", 2, [100, 101])  # 29 + 30 April
    out = to_monthly_close(df, as_of=pd.Timestamp("2026-04-30"))
    assert list(out.index) == []


def test_price_return_only_when_no_dividends() -> None:
    df = _daily("2024-01-30", 5, [100, 100, 100, 110, 110])
    out = monthly_total_returns(df, [], tax=0.13)
    jan = pd.Period("2024-01", "M")
    feb = pd.Period("2024-02", "M")
    assert math.isnan(out.loc[jan, "total_return"])
    assert math.isclose(out.loc[feb, "price_return"], 0.1)
    assert out.loc[feb, "div_return"] == 0.0
    assert math.isclose(out.loc[feb, "total_return"], 0.1)


def test_div_slag_in_month() -> None:
    """Dividend 10 ₽ ex on day-2 (close_pre_ex = 100), tax 0.13:
    slag = 0.87 * 10 / 100 = 0.087."""
    df = _daily("2024-01-30", 5, [100, 100, 100, 110, 110])
    divs = [{"registry_close": "2024-01-31", "amount_adj": 10.0}]
    out = monthly_total_returns(df, divs, tax=0.13)
    jan = pd.Period("2024-01", "M")
    # ex=2024-01-31, prior close = 2024-01-30 = 100.
    assert math.isclose(out.loc[jan, "div_return"], 0.087)


def test_multiple_dividends_in_one_month_sum() -> None:
    df = _daily("2024-01-30", 5, [100, 100, 100, 100, 100])
    divs = [
        {"registry_close": "2024-01-31", "amount_adj": 5.0},
        {"registry_close": "2024-02-01", "amount_adj": 5.0},
    ]
    out = monthly_total_returns(df, divs, tax=0.0)
    feb = pd.Period("2024-02", "M")
    # 2024-01-31 contributes to Jan, 2024-02-01 to Feb.
    jan = pd.Period("2024-01", "M")
    assert math.isclose(out.loc[jan, "div_return"], 0.05)
    assert math.isclose(out.loc[feb, "div_return"], 0.05)


def test_dividend_before_first_price_skipped() -> None:
    df = _daily("2024-02-01", 3, [100, 100, 100])
    divs = [{"registry_close": "2024-01-15", "amount_adj": 1.0}]
    out = monthly_total_returns(df, divs, tax=0.0)
    feb = pd.Period("2024-02", "M")
    assert out.loc[feb, "div_return"] == 0.0


def test_split_dividend_invariance_when_paid_before_the_split() -> None:
    """A payout strictly before the split: amount and close scale by the same
    factor, so the tax-adjusted yield is unchanged by the split."""
    raw_rows = [
        {"date": "2024-04-24", "close": 100.0, "value": 1.0},
        {"date": "2024-04-25", "close": 100.0, "value": 1.0},
        {"date": "2024-04-30", "close": 100.0, "value": 1.0},
        {"date": "2024-05-01", "close": 50.0, "value": 1.0},  # split D
        {"date": "2024-05-31", "close": 55.0, "value": 1.0},
    ]
    splits = [{"date": "2024-05-01", "before": 1, "after": 2, "type": "f", "source": "t"}]
    divs = [{"registry_close": "2024-04-26", "amount": 10.0, "currency": "RUB", "source": "t"}]
    prices_adj_df = apply_splits_to_prices(raw_rows, splits)
    divs_adj = adjust_dividend_amounts(divs, splits)
    assert divs_adj[0]["amount_adj"] == 5.0  # paid before D → scaled with the prices
    out = monthly_total_returns(prices_adj_df, divs_adj, tax=0.13)
    # 0.87 * 5 / 50 == 0.87 * 10 / 100 — the split cancels.
    assert math.isclose(out.loc[pd.Period("2024-04", "M"), "div_return"], 0.087)


def test_dividend_on_the_split_date_uses_the_post_split_scale() -> None:
    """The split date itself is already post-split (`apply.py`), so the amount is not
    scaled while the pre-ex close is — the ratio is 0.174, not 0.087.

    Boundary case; the invariance the pipeline actually promises is the test below.
    """
    raw_rows = [
        {"date": "2024-04-29", "close": 100.0, "value": 1.0},
        {"date": "2024-04-30", "close": 100.0, "value": 1.0},  # close_pre_ex
        {"date": "2024-05-01", "close": 50.0, "value": 1.0},  # split D + ex_date
        {"date": "2024-05-02", "close": 55.0, "value": 1.0},
        {"date": "2024-05-31", "close": 55.0, "value": 1.0},
    ]
    splits = [{"date": "2024-05-01", "before": 1, "after": 2, "type": "f", "source": "t"}]
    divs = [
        {"registry_close": "2024-05-01", "amount": 10.0, "currency": "RUB", "source": "t"},
    ]
    prices_adj_df = apply_splits_to_prices(raw_rows, splits)
    divs_adj = adjust_dividend_amounts(divs, splits)
    # ex == split date → no scaling for amount or close.
    assert divs_adj[0]["amount_adj"] == 10.0
    out = monthly_total_returns(prices_adj_df, divs_adj, tax=0.13)
    may = pd.Period("2024-05", "M")
    # close_pre_ex_adj = adj close on 2024-04-30 = 100*0.5 = 50. amount_adj = 10.
    # slag = 0.87 * 10 / 50 = 0.174.
    assert math.isclose(out.loc[may, "div_return"], 0.174)


def test_empty_input_returns_empty() -> None:
    out = monthly_total_returns(pd.DataFrame(columns=["close_adj"]), [], tax=0.13)
    assert out.empty


def test_zero_tax_passes_full_div() -> None:
    df = _daily("2024-01-30", 5, [100, 100, 100, 100, 100])
    divs = [{"registry_close": "2024-01-31", "amount_adj": 5.0}]
    out = monthly_total_returns(df, divs, tax=0.0)
    jan = pd.Period("2024-01", "M")
    assert math.isclose(out.loc[jan, "div_return"], 0.05)


def test_trading_gap_does_not_create_synthetic_return() -> None:
    """A 3-year trading gap must NOT produce a single huge monthly return
    spanning it (the ERCO 2013-10 → 2016-11 case). Without the reindex fix,
    `pct_change` between adjacent records yields +5800% as a "monthly" return.
    With the fix, the first traded month after the gap has NaN price_return.
    """
    idx = pd.DatetimeIndex(
        [
            pd.Timestamp("2013-10-10"),
            pd.Timestamp("2013-10-25"),
            # 3-year gap, no trades
            pd.Timestamp("2016-11-03"),
            pd.Timestamp("2016-11-29"),
            pd.Timestamp("2016-12-12"),
        ]
    )
    df = pd.DataFrame({"close_adj": [7.0, 7.013, 412.45, 412.41, 412.97]}, index=idx)
    out = monthly_total_returns(df, [], tax=0.0)
    months = [str(p) for p in out.index]
    assert "2013-10" in months
    assert "2016-11" in months
    assert "2016-12" in months
    assert "2014-05" not in months  # gap month emitted by reindex but dropped
    # The first traded month after the gap MUST have NaN price_return
    # (instead of +5789% which is what naive pct_change would yield).
    pr_post_gap = out.loc[pd.Period("2016-11", "M"), "price_return"]
    assert math.isnan(pr_post_gap)
    # And the next month resumes normally — small return ≈ 0.13%.
    pr_dec = out.loc[pd.Period("2016-12", "M"), "price_return"]
    assert math.isclose(pr_dec, 412.97 / 412.41 - 1, abs_tol=1e-9)


def _daily_with_value(start: str, n: int, closes: list[float], values: list[float]) -> pd.DataFrame:
    d0 = date.fromisoformat(start)
    idx = pd.DatetimeIndex([d0 + timedelta(days=i) for i in range(n)])
    return pd.DataFrame({"close_adj": closes, "value": values}, index=idx)


def test_monthly_value_sums_the_daily_turnover() -> None:
    """The top-100 liquidity cut rides on this sum, so a wrong one reshapes every quartile."""
    df = _daily_with_value("2024-01-30", 4, [100.0, 101.0, 102.0, 103.0], [1e6, 2e6, 4e6, 8e6])
    out = to_monthly_close(df, as_of=pd.Timestamp("2024-03-01"))
    assert out.loc[pd.Period("2024-01", "M"), "monthly_value_rub"] == 3e6
    assert out.loc[pd.Period("2024-02", "M"), "monthly_value_rub"] == 12e6


def test_monthly_value_is_zero_without_a_value_column() -> None:
    """A price file with no `value` reads as zero turnover, not as missing — it
    silently sinks to the bottom of the liquidity ranking."""
    df = _daily("2024-01-30", 4, [100.0, 101.0, 102.0, 103.0])
    out = to_monthly_close(df, as_of=pd.Timestamp("2024-03-01"))
    assert list(out["monthly_value_rub"]) == [0.0, 0.0]


def test_untraded_month_carries_no_turnover_figure() -> None:
    """A gap month is NaN, not 0.0 — `monthly_total_returns` drops those rows, so a
    real zero (a file without `value`) and a non-traded month stay distinguishable."""
    df = _daily_with_value("2024-01-15", 1, [100.0], [5e6])
    march = _daily_with_value("2024-03-15", 1, [110.0], [7e6])
    out = to_monthly_close(pd.concat([df, march]), as_of=pd.Timestamp("2024-04-01"))
    assert pd.isna(out.loc[pd.Period("2024-02", "M"), "monthly_value_rub"])
    assert pd.isna(out.loc[pd.Period("2024-02", "M"), "close_adj"])


def test_trailing_month_is_kept_without_an_explicit_cutoff() -> None:
    """No `as_of` means no cutoff: the leaf never reads the clock, so the same
    inputs give the same months whenever the build runs."""
    today = pd.Timestamp.now().normalize()
    start = today.replace(day=1)
    df = _daily(str(start.date()), 3, [100.0, 101.0, 102.0])
    assert to_monthly_close(df).index[-1] == start.to_period("M")


def test_explicit_cutoff_drops_the_in_progress_month() -> None:
    today = pd.Timestamp.now().normalize()
    start = today.replace(day=1)
    df = _daily(str(start.date()), 3, [100.0, 101.0, 102.0])
    out = to_monthly_close(df, as_of=df.index.max() + pd.Timedelta(days=1))
    assert start.to_period("M") not in out.index


def test_delisted_ticker_keeps_its_partial_final_month() -> None:
    """A delisting ends mid-month by definition. The run-wide cutoff sits far
    later, so that month survives — a per-ticker cutoff would strip it."""
    df = _daily("2018-06-11", 5, [100.0, 101.0, 102.0, 103.0, 104.0])
    out = to_monthly_close(df, as_of=pd.Timestamp("2026-09-05"))
    assert out.index[-1] == pd.Period("2018-06", "M")
