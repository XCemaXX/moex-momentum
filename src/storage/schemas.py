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
# `split_adjusted_back_by`: legacy field from earlier split-adjust pass.
# No source writes it today, but a few records still carry it — preserve on round-trip.
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
Q_VALUES_FIELDS: tuple[str, ...] = ("month", "Q1", "Q2", "Q3", "Q4", "MCFTRR")
Q_VALUES_CASTS: Mapping[str, Callable[[str], object]] = {
    "Q1": float,
    "Q2": float,
    "Q3": float,
    "Q4": float,
    "MCFTRR": float,
}
