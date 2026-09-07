"""Daily adjusted prices + adjusted dividends → monthly total returns.

Total-return formula (plan §8):

    total_return[m] = (close_adj[m] / close_adj[m-1]) - 1
                    + sum_{div in (m-1, m]} (1 - tax) * amount_adj / close_pre_ex_adj

`close_pre_ex_adj` is the adjusted close on the trading day before the ex-date,
and the payout is booked into the ex-date's month. Only `skill_fill_yahoo` stores
the ex-date in `registry_close`; every other source stores the RECORD date, which
falls `SETTLEMENT_LAG` trading days later. Dividing by a post-gap close would
inflate the yield by ~1/(1-y) — see `task 036`.

Dividends preceding the first available price are dropped with a WARN, as are
those whose ex-date lands in a trading gap: there the anchor is not a price the
payout was ever measured against.
"""

from __future__ import annotations

import logging
from typing import Any, cast

import pandas as pd

from config import EX_DATE_SOURCE, LOG_SAMPLE, SETTLEMENT_T1_FROM, SETTLEMENT_T2_FROM

LOG = logging.getLogger(__name__)


def _settlement_lag(source: str, registry_close: pd.Timestamp) -> int:
    """Trading days from the ex-date to the stored `registry_close`."""
    if source == EX_DATE_SOURCE:
        return 1
    if registry_close < pd.Timestamp(SETTLEMENT_T2_FROM):
        return 0
    if registry_close < pd.Timestamp(SETTLEMENT_T1_FROM):
        return 2
    return 1


def to_monthly_close(
    prices_adj_df: pd.DataFrame,
    *,
    as_of: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Last trading day of each calendar month, reindexed to a CONTIGUOUS
    Period[M] range from the first traded month to the last.

    A month with no trades gets a NaN row. This ensures `pct_change()` cannot
    silently span multi-month trading gaps (e.g. ERCO's 2013-10→2016-11 gap
    would otherwise produce a single +57× «monthly» return).

    The trailing period is dropped if `as_of <= period.end_time` — i.e. the
    month is still in progress (mid-month or last trading day's close not yet
    settled). Default `as_of = today UTC normalized`; pass an explicit value
    for deterministic tests. See methodology «Конвенция периода».

    Returns DataFrame indexed by Period[M] with columns:
        - month_end_date (Timestamp; NaT for missing months)
        - close_adj (float; NaN for missing months)
        - monthly_value_rub (float; sum of daily `value` for the month,
          0.0 for missing months — liquidity proxy used by the universe filter)
    """
    if prices_adj_df.empty:
        return pd.DataFrame(
            {
                "month_end_date": pd.Series(dtype="datetime64[ns]"),
                "close_adj": pd.Series(dtype=float),
                "monthly_value_rub": pd.Series(dtype=float),
            }
        )
    idx = cast(pd.DatetimeIndex, prices_adj_df.index)
    period = idx.to_period("M")
    grp = prices_adj_df.groupby(period)
    last_idx = cast(pd.DatetimeIndex, grp.tail(1).index)
    if "value" in prices_adj_df.columns:
        monthly_value = grp["value"].sum().astype(float)
    else:
        monthly_value = pd.Series(0.0, index=grp.size().index, dtype=float)
    traded = pd.DataFrame(
        {
            "month_end_date": last_idx,
            "close_adj": prices_adj_df.loc[last_idx, "close_adj"].astype(float).values,
            "monthly_value_rub": monthly_value.values,
        },
        index=last_idx.to_period("M"),
    )
    full_idx = pd.period_range(start=traded.index[0], end=traded.index[-1], freq="M")
    out = traded.reindex(full_idx)
    out.index.name = "month"
    cutoff = as_of if as_of is not None else pd.Timestamp("now").normalize()
    if len(out) > 0 and cutoff <= out.index[-1].end_time:
        out = out.iloc[:-1]
    return out


def monthly_total_returns(
    prices_adj_df: pd.DataFrame,
    dividends_adj: list[dict[str, Any]],
    *,
    tax: float,
    ticker: str | None = None,
    as_of: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Returns DataFrame indexed by Period[M] with columns:
        month_end_date, close_adj, price_return, div_return, total_return.

    First month has NaN returns (no prior close). `as_of` is passed through
    to `to_monthly_close` to drop the in-progress trailing month.
    """
    monthly = to_monthly_close(prices_adj_df, as_of=as_of)
    if monthly.empty:
        return pd.DataFrame(
            {
                "month_end_date": pd.Series(dtype="datetime64[ns]"),
                "close_adj": pd.Series(dtype=float),
                "monthly_value_rub": pd.Series(dtype=float),
                "price_return": pd.Series(dtype=float),
                "div_return": pd.Series(dtype=float),
                "total_return": pd.Series(dtype=float),
            }
        )
    monthly["price_return"] = monthly["close_adj"].pct_change()

    div_slag_by_month: dict[pd.Period, float] = {}
    idx = cast(pd.DatetimeIndex, prices_adj_df.index)
    before_first_price: list[str] = []
    non_positive_close: list[str] = []
    stale_anchor: list[str] = []
    for d in dividends_adj:
        reg = pd.Timestamp(d["registry_close"])
        last = int(idx.searchsorted(reg, side="right")) - 1
        ex_pos = last - _settlement_lag(str(d.get("source", "")), reg) + 1
        if ex_pos <= 0:
            before_first_price.append(str(d["registry_close"]))
            continue
        if ex_pos >= len(idx):
            stale_anchor.append(str(d["registry_close"]))
            continue
        ex = idx[ex_pos]
        # The lag is at most two trading days, so a legitimate ex-date shares the
        # record date's month or an adjacent one. Anything further means we stepped
        # into a trading gap: 190 such rows exist, and dividing a 2019 payout by a
        # 2012 close implies yields up to 136%.
        m = ex.to_period("M")
        if not (reg.to_period("M") - 1 <= m <= reg.to_period("M") + 1):
            stale_anchor.append(str(d["registry_close"]))
            continue
        close_pre_ex_adj = float(prices_adj_df.iloc[ex_pos - 1]["close_adj"])
        if close_pre_ex_adj <= 0:
            non_positive_close.append(str(d["registry_close"]))
            continue
        amt = float(d["amount_adj"])
        slag = (1.0 - tax) * amt / close_pre_ex_adj
        div_slag_by_month[m] = div_slag_by_month.get(m, 0.0) + slag

    if before_first_price:
        LOG.warning(
            "dividend before first price, skipped ticker=%s n=%d sample_ex=%s",
            ticker,
            len(before_first_price),
            ",".join(before_first_price[:LOG_SAMPLE]),
        )
    if stale_anchor:
        LOG.warning(
            "dividend ex-date lands in a trading gap, skipped ticker=%s n=%d sample_reg=%s",
            ticker,
            len(stale_anchor),
            ",".join(stale_anchor[:LOG_SAMPLE]),
        )
    if non_positive_close:
        LOG.warning(
            "dividend pre-ex close non-positive, skipped ticker=%s n=%d sample_ex=%s",
            ticker,
            len(non_positive_close),
            ",".join(non_positive_close[:LOG_SAMPLE]),
        )

    monthly["div_return"] = [div_slag_by_month.get(p, 0.0) for p in monthly.index]
    monthly["total_return"] = monthly["price_return"].fillna(0.0) + monthly["div_return"]
    monthly.loc[monthly["price_return"].isna(), "total_return"] = float("nan")
    # Drop reindexed gap rows (no trading that month) — they carry NaN close
    # and would crash JSONL serialization.
    monthly = monthly[monthly["close_adj"].notna()]
    return monthly[
        [
            "month_end_date",
            "close_adj",
            "monthly_value_rub",
            "price_return",
            "div_return",
            "total_return",
        ]
    ]
