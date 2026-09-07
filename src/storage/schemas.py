"""Per-domain CSV schemas: column order + type casts for read_records."""

from __future__ import annotations

from collections.abc import Callable, Mapping

# data/prices_iss/{TICKER}.csv
PRICE_FIELDS: tuple[str, ...] = (
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "value",
    "board",
)
PRICE_CASTS: Mapping[str, Callable[[str], object]] = {
    "open": float,
    "high": float,
    "low": float,
    "close": float,
    "volume": int,
    "value": float,
}

# data/dividends/{TICKER}.csv
# `split_adjusted_back_by`: provenance, not a split lookup. Marks rows whose amount
# THIS pipeline lifted onto the stored share scale (`ingest.dividends.scale`), because
# the feed quoted it at today's count. `data/splits/` cannot answer that: an ISS row
# and a rescaled yahoo row before the same split are indistinguishable without it.
DIV_FIELDS: tuple[str, ...] = (
    "registry_close",
    "amount",
    "currency",
    "source",
    "registry_close_source",
    "split_adjusted_back_by",
)
DIV_CASTS: Mapping[str, Callable[[str], object]] = {
    "amount": float,
    "split_adjusted_back_by": float,
}

# data/splits/{TICKER}.csv
SPLIT_FIELDS: tuple[str, ...] = ("date", "before", "after", "type", "source")
SPLIT_CASTS: Mapping[str, Callable[[str], object]] = {"before": int, "after": int}

# data/indices/{INDEX}.csv
INDEX_FIELDS: tuple[str, ...] = ("date", "close")
INDEX_CASTS: Mapping[str, Callable[[str], object]] = {"close": float}

# data/momentum/monthly/{TICKER}.csv
MONTHLY_FIELDS: tuple[str, ...] = (
    "month",
    "month_end_date",
    "close_adj",
    "monthly_value_rub",
    "price_return",
    "div_return",
    "total_return",
)
MONTHLY_CASTS: Mapping[str, Callable[[str], object]] = {
    "close_adj": float,
    "monthly_value_rub": float,
    "price_return": float,
    "div_return": float,
    "total_return": float,
}

# data/momentum/{signal}/q_values.csv
SCORES_FIELDS: tuple[str, ...] = ("month", "ticker", "score")
SCORES_CASTS: Mapping[str, Callable[[str], object]] = {"score": float}

# `cut_rub` is empty in months where the universe did not reach the liquidity cap.
UNIVERSE_META_FIELDS: tuple[str, ...] = ("month", "n", "cut_rub", "marginal")

Q_VALUES_FIELDS: tuple[str, ...] = ("month", "Q1", "Q2", "Q3", "Q4", "MCFTRR")
Q_VALUES_CASTS: Mapping[str, Callable[[str], object]] = {
    "Q1": float,
    "Q2": float,
    "Q3": float,
    "Q4": float,
    "MCFTRR": float,
}
