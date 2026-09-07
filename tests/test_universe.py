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


def _rename_panel(tmp_path: Path) -> tuple[Path, list[str]]:
    """OLD renamed into NEW; NEW carries the stitched history, so both files
    exist and both are eligible in every month."""
    months = [str(pd.Period("2020-01", "M") + i) for i in range(15)]
    returns: list[float | None] = [None, *[0.01] * 14]
    _write_monthly(tmp_path, "OLD", months, returns)
    _write_monthly(tmp_path, "NEW", months, returns)
    _write_monthly(tmp_path, "OTHER", months, returns, monthly_value=1e7)
    return tmp_path, months


def test_renamed_predecessor_hands_over_at_the_rename_month(tmp_path: Path) -> None:
    monthly_dir, _ = _rename_panel(tmp_path)
    returns_panel, _c, value_panel = load_panel(monthly_dir)
    tickers = {
        "OLD": {"type": "share"},
        "NEW": {
            "type": "share",
            "history": [
                {"prev_ticker": "OLD", "renamed": "2021-02-10", "source": "iss_changeover"}
            ],
        },
        "OTHER": {"type": "share"},
    }
    for month, expected in (("2021-01", "OLD"), ("2021-02", "NEW")):
        got = universe_at(
            pd.Period(month, "M"), returns_panel, tickers, value_panel=value_panel, top_n=2
        )
        assert expected in got, f"{month}: {expected} missing"
        assert len([tk for tk in got if tk in ("OLD", "NEW")]) == 1, f"{month}: both legs present"
        # The freed slot is refilled, not lost.
        assert len(got) == 2


def test_redomicile_history_is_not_treated_as_a_rename(tmp_path: Path) -> None:
    """Only `iss_changeover` bridges a ticker; a manual entry is another security."""
    monthly_dir, _ = _rename_panel(tmp_path)
    returns_panel, _c, value_panel = load_panel(monthly_dir)
    tickers = {
        "OLD": {"type": "share"},
        "NEW": {
            "type": "share",
            "history": [{"prev_ticker": "OLD", "renamed": "2021-02-10", "source": "manual"}],
        },
    }
    got = universe_at(
        pd.Period("2021-02", "M"), returns_panel, tickers, value_panel=value_panel, top_n=5
    )
    assert {"OLD", "NEW"} <= set(got)


def test_self_referencing_history_is_not_a_rename(tmp_path: Path) -> None:
    """Some dictionary entries name the SECID as its own predecessor. Reading that
    as a rename delists the name outright — it did exactly that to SBER."""
    monthly_dir, _ = _rename_panel(tmp_path)
    returns_panel, _c, value_panel = load_panel(monthly_dir)
    tickers = {
        "OLD": {
            "type": "share",
            "history": [
                {"prev_ticker": "OLD", "renamed": "2020-06-01", "source": "iss_changeover"}
            ],
        },
    }
    got = universe_at(
        pd.Period("2021-02", "M"), returns_panel, tickers, value_panel=value_panel, top_n=5
    )
    assert got == ["OLD"]
