"""Daily adjusted prices + adjusted dividends → monthly total returns.

Total-return formula (plan §8):

    total_return[m] = (close_adj[m] / close_adj[m-1]) - 1
                    + sum_{div in (m-1, m]} (1 - tax) * amount_adj / close_pre_ex_adj

`close_pre_ex_adj` is the adjusted close on the last trading day STRICTLY
BEFORE the dividend's ex-date (registry_close). Dividends preceding the
first available price are dropped with a WARN — there is no pre-ex close
to scale against.
"""

from __future__ import annotations

import logging
from typing import Any, cast

import pandas as pd

LOG = logging.getLogger(__name__)


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
    for d in dividends_adj:
        ex = pd.Timestamp(d["registry_close"])
        pos = int(idx.searchsorted(ex, side="left"))
        if pos == 0:
            LOG.warning(
                "dividend before first price ticker=%s ex=%s amount=%s — skipped",
                ticker,
                d["registry_close"],
                d.get("amount"),
            )
            continue
        close_pre_ex_adj = float(prices_adj_df.iloc[pos - 1]["close_adj"])
        if close_pre_ex_adj <= 0:
            LOG.warning(
                "dividend pre-ex close non-positive ticker=%s ex=%s — skipped",
                ticker,
                d["registry_close"],
            )
            continue
        amt = float(d["amount_adj"])
        slag = (1.0 - tax) * amt / close_pre_ex_adj
        m = ex.to_period("M")
        div_slag_by_month[m] = div_slag_by_month.get(m, 0.0) + slag

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
