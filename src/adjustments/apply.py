"""Back-adjustment of raw daily prices to the latest split scale, plus
matching dividend-amount scaling.

Convention (locked in plan §8): a split (D, before=B, after=A) multiplies
every close STRICTLY BEFORE D by `c = B/A`. The split date D itself is
already on the post-split scale and is untouched. The same `c` applies to
dividend amounts paid strictly before D.
"""

from __future__ import annotations

import logging
from typing import Any, cast

import pandas as pd

from ingest.dividends.merge import dedup_near_duplicates

LOG = logging.getLogger(__name__)


def _parse_splits(splits: list[dict[str, Any]]) -> list[tuple[pd.Timestamp, float]]:
    out: list[tuple[pd.Timestamp, float]] = []
    for s in splits:
        before = float(s["before"])
        after = float(s["after"])
        if before <= 0 or after <= 0:
            raise ValueError(f"split {s}: before/after must be positive")
        out.append((pd.Timestamp(s["date"]), before / after))
    out.sort(key=lambda x: x[0])
    return out


def cascade_for_dates(
    dates: pd.DatetimeIndex,
    splits: list[dict[str, Any]],
) -> pd.Series:
    """For each date in `dates`, the product of `B/A` over splits with `D > date`.

    A date that lies AT a split's D (or later than all splits) gets coefficient 1
    for that split.
    """
    coef = pd.Series(1.0, index=dates)
    for split_date, c in _parse_splits(splits):
        coef.loc[dates < split_date] *= c
    return coef


def apply_splits_to_prices(
    prices: list[dict[str, Any]],
    splits: list[dict[str, Any]],
) -> pd.DataFrame:
    """Indexed by date (datetime). Columns: close_raw, close_adj, value (if present).

    Filters out rows with close<=0 (pre-2010 MOEX artefacts) to keep downstream
    returns finite.
    """
    if not prices:
        return pd.DataFrame(columns=["close_raw", "close_adj", "value"]).astype(
            {"close_raw": float, "close_adj": float, "value": float}
        )
    df = pd.DataFrame(prices)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    df = df.rename(columns={"close": "close_raw"})
    df["close_raw"] = df["close_raw"].astype(float)
    df = df[df["close_raw"] > 0]
    if df.empty:
        return pd.DataFrame(columns=["close_raw", "close_adj", "value"]).astype(
            {"close_raw": float, "close_adj": float, "value": float}
        )
    coef = cascade_for_dates(cast(pd.DatetimeIndex, df.index), splits)
    df["close_adj"] = df["close_raw"] * coef
    cols = ["close_raw", "close_adj"]
    if "value" in df.columns:
        df["value"] = df["value"].astype(float)
        cols.append("value")
    return df[cols]


def adjust_dividend_amounts(
    dividends: list[dict[str, Any]],
    splits: list[dict[str, Any]],
    *,
    ticker: str | None = None,
) -> list[dict[str, Any]]:
    """Returns RUB-only dividends with an extra `amount_adj` field.

    Non-RUB records are dropped with a WARN — FX conversion is out of scope
    for the momentum pipeline (affects 9 records: RUAL 2022, POLY 2015-2018).
    """
    if not dividends:
        return []
    rub: list[dict[str, Any]] = []
    for d in dividends:
        cur = d.get("currency", "RUB")
        if cur != "RUB":
            LOG.warning(
                "dividend skipped (non-RUB) ticker=%s ex=%s currency=%s amount=%s",
                ticker,
                d.get("registry_close"),
                cur,
                d.get("amount"),
            )
            continue
        rub.append(d)
    if not rub:
        return []
    # Collapse cross-source near-duplicates so monthly_total_returns never
    # double-counts (e.g. moex_iss + manual_disclosure for the same payout).
    deduped, dropped = dedup_near_duplicates(rub)
    for r in dropped:
        LOG.warning(
            "dividend dropped as near-dup ticker=%s ex=%s amount=%s source=%s",
            ticker,
            r.get("registry_close"),
            r.get("amount"),
            r.get("source"),
        )
    rub = deduped
    idx = pd.DatetimeIndex([pd.Timestamp(d["registry_close"]) for d in rub])
    coef = cascade_for_dates(idx, splits)
    out: list[dict[str, Any]] = []
    for d, c in zip(rub, coef, strict=True):
        out.append({**d, "amount_adj": float(d["amount"]) * float(c)})
    return out
