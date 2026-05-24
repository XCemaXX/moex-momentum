"""Universe filter tests."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from momentum.universe import load_panel, universe_at
from storage.records import write_records_atomic
from storage.schemas import MONTHLY_FIELDS


def _write_monthly(
    dir: Path,
    ticker: str,
    months: list[str],
    returns: list[float | None],
    monthly_value: float = 1e8,
) -> None:
    rows: list[dict[str, object]] = []
    for m, r in zip(months, returns, strict=True):
        period = pd.Period(m, freq="M")
        end = period.to_timestamp(how="end").date().isoformat()
        rows.append(
            {
                "month": m,
                "month_end_date": end,
                "close_adj": 100.0,
                "monthly_value_rub": monthly_value,
                "price_return": r,
                "div_return": 0.0,
                "total_return": r,
            }
        )
    write_records_atomic(dir / f"{ticker}.csv", rows, fieldnames=MONTHLY_FIELDS)


def test_load_panel_empty_dir(tmp_path: Path) -> None:
    r, c, _v = load_panel(tmp_path)
    assert r.empty
    assert c.empty


def test_load_panel_wide_shape(tmp_path: Path) -> None:
    _write_monthly(tmp_path, "A", ["2022-01", "2022-02"], [None, 0.05])
    _write_monthly(tmp_path, "B", ["2022-02", "2022-03"], [None, 0.10])
    returns, _, _v = load_panel(tmp_path)
    assert set(returns.columns) == {"A", "B"}
    assert len(returns.index) == 3  # 2022-01, 02, 03
    assert pd.isna(returns.loc[pd.Period("2022-01", "M"), "A"])
    assert returns.loc[pd.Period("2022-03", "M"), "B"] == 0.10


def test_universe_requires_full_window(tmp_path: Path) -> None:
    # Ticker A: 13 consecutive months ending 2023-01 → eligible.
    months = [str(pd.Period("2022-01", "M") + i) for i in range(13)]
    returns: list[float | None] = [None] + [0.01] * 12
    _write_monthly(tmp_path, "A", months, returns)
    panel, _, _v = load_panel(tmp_path)
    tickers_dict = {"A": {"type": "share"}}
    u = universe_at(pd.Period("2023-01", "M"), panel, tickers_dict)
    assert u == ["A"]
    # One month earlier — window doesn't fit yet.
    u_short = universe_at(pd.Period("2022-12", "M"), panel, tickers_dict)
    assert u_short == []


def test_universe_excludes_non_share(tmp_path: Path) -> None:
    months = [str(pd.Period("2022-01", "M") + i) for i in range(13)]
    returns: list[float | None] = [None] + [0.01] * 12
    _write_monthly(tmp_path, "A", months, returns)
    _write_monthly(tmp_path, "B", months, returns)
    panel, _, _v = load_panel(tmp_path)
    tickers_dict: dict = {"A": {"type": "share"}, "B": {"type": "etf"}}
    u = universe_at(pd.Period("2023-01", "M"), panel, tickers_dict)
    assert u == ["A"]


def test_universe_respects_delisted_after(tmp_path: Path) -> None:
    months = [str(pd.Period("2022-01", "M") + i) for i in range(13)]
    returns: list[float | None] = [None] + [0.01] * 12
    _write_monthly(tmp_path, "A", months, returns)
    panel, _, _v = load_panel(tmp_path)
    t = pd.Period("2023-01", "M")
    # Delisted before t-month-end → excluded.
    excluded = {"A": {"type": "share", "delisted_after": "2022-12-15"}}
    assert universe_at(t, panel, excluded) == []
    # Delisted after t-month-end → included.
    included = {"A": {"type": "share", "delisted_after": "2023-02-01"}}
    assert universe_at(t, panel, included) == ["A"]


def test_universe_excludes_ticker_with_nan_in_window(tmp_path: Path) -> None:
    months = [str(pd.Period("2022-01", "M") + i) for i in range(13)]
    # NaN at month 5 inside the [t-11..t] window.
    returns: list[float | None] = [None] + [0.01] * 4 + [None] + [0.01] * 7
    _write_monthly(tmp_path, "A", months, returns)
    panel, _, _v = load_panel(tmp_path)
    tickers_dict = {"A": {"type": "share"}}
    assert universe_at(pd.Period("2023-01", "M"), panel, tickers_dict) == []


def test_universe_alphabetical_order(tmp_path: Path) -> None:
    months = [str(pd.Period("2022-01", "M") + i) for i in range(13)]
    returns: list[float | None] = [None] + [0.01] * 12
    for tk in ["GAZP", "AFLT", "SBER"]:
        _write_monthly(tmp_path, tk, months, returns)
    panel, _, _v = load_panel(tmp_path)
    tickers_dict = {tk: {"type": "share"} for tk in ["GAZP", "AFLT", "SBER"]}
    u = universe_at(pd.Period("2023-01", "M"), panel, tickers_dict)
    assert u == ["AFLT", "GAZP", "SBER"]


def test_universe_top_n_keeps_most_liquid(tmp_path: Path) -> None:
    """top_n keeps the N most liquid names by trailing median monthly value."""
    months = [str(pd.Period("2022-01", "M") + i) for i in range(13)]
    returns: list[float | None] = [None] + [0.01] * 12
    _write_monthly(tmp_path, "HIGH", months, returns, monthly_value=1e9)
    _write_monthly(tmp_path, "MID", months, returns, monthly_value=1e7)
    _write_monthly(tmp_path, "LOW", months, returns, monthly_value=1e5)
    panel, _, vpanel = load_panel(tmp_path)
    tickers_dict = {tk: {"type": "share"} for tk in ["HIGH", "MID", "LOW"]}
    t = pd.Period("2023-01", "M")

    # No top_n — all eligible names included.
    assert universe_at(t, panel, tickers_dict) == ["HIGH", "LOW", "MID"]
    # top_n=2 — the two most liquid kept (returned alphabetically).
    assert universe_at(t, panel, tickers_dict, value_panel=vpanel, top_n=2) == ["HIGH", "MID"]
    # top_n=1 — only the most liquid.
    assert universe_at(t, panel, tickers_dict, value_panel=vpanel, top_n=1) == ["HIGH"]
