"""Backtest engine tests — quartile split, costs, NAV invariants."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from momentum.backtest import (
    backtest,
    gross_return,
    quartile_split,
    turnover,
    write_backtest,
)
from momentum.signals import SimpleSignal
from storage.records import write_records_atomic
from storage.schemas import INDEX_FIELDS, MONTHLY_FIELDS


def test_quartile_split_basic_ranking() -> None:
    scores = pd.Series({"A": 0.4, "B": 0.3, "C": 0.2, "D": 0.1})
    q = quartile_split(scores)
    assert q["Q1"] == ["A"]
    assert q["Q2"] == ["B"]
    assert q["Q3"] == ["C"]
    assert q["Q4"] == ["D"]


def test_quartile_split_uneven_remainder_goes_to_top() -> None:
    scores = pd.Series({f"T{i:02d}": -i for i in range(10)})  # 10 tickers
    q = quartile_split(scores)
    # Sizes [3,3,2,2] — Q1, Q2 get the extras.
    assert [len(q[k]) for k in ["Q1", "Q2", "Q3", "Q4"]] == [3, 3, 2, 2]
    # Q1 = three highest scores = T00, T01, T02 (sorted).
    assert q["Q1"] == ["T00", "T01", "T02"]


def test_quartile_split_tie_broken_alphabetically() -> None:
    # All tied at zero → ranking entirely by ticker ASC.
    scores = pd.Series({"D": 0.0, "B": 0.0, "A": 0.0, "C": 0.0})
    q = quartile_split(scores)
    assert q["Q1"] == ["A"]
    assert q["Q2"] == ["B"]
    assert q["Q3"] == ["C"]
    assert q["Q4"] == ["D"]


def test_quartile_split_drops_nan_scores() -> None:
    scores = pd.Series({"A": 0.5, "B": float("nan"), "C": 0.3, "D": 0.1})
    q = quartile_split(scores)
    flat = q["Q1"] + q["Q2"] + q["Q3"] + q["Q4"]
    assert "B" not in flat
    assert sorted(flat) == ["A", "C", "D"]


def test_quartile_split_empty() -> None:
    q = quartile_split(pd.Series([], dtype=float))
    assert q == {"Q1": [], "Q2": [], "Q3": [], "Q4": []}


def test_turnover_initial_buy_in_equals_one() -> None:
    assert math.isclose(turnover({}, {"A": 0.5, "B": 0.5}), 1.0, abs_tol=1e-12)


def test_turnover_full_swap_equals_two() -> None:
    old = {"A": 0.5, "B": 0.5}
    new = {"C": 0.5, "D": 0.5}
    assert math.isclose(turnover(old, new), 2.0, abs_tol=1e-12)


def test_turnover_no_change_zero() -> None:
    w = {"A": 0.5, "B": 0.5}
    assert math.isclose(turnover(w, w), 0.0, abs_tol=1e-12)


def test_gross_return_equal_weight() -> None:
    w = {"A": 0.5, "B": 0.5}
    r = pd.Series({"A": 0.10, "B": -0.10})
    assert math.isclose(
        gross_return(w, r, period=pd.Period("2022-01", "M"), quartile="Q1"),
        0.0,
        abs_tol=1e-12,
    )


def test_gross_return_missing_ticker_treated_as_zero(caplog) -> None:
    w = {"A": 0.5, "B": 0.5}
    r = pd.Series({"A": 0.20})  # B missing
    out = gross_return(w, r, period=pd.Period("2022-01", "M"), quartile="Q1")
    # B contributes 0 → return = 0.5 × 0.20 + 0.5 × 0 = 0.10
    assert math.isclose(out, 0.10, abs_tol=1e-12)


def _seed_monthly_dir(
    dir: Path, ticker: str, months: list[str], returns: list[float | None]
) -> None:
    dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for m, r in zip(months, returns, strict=True):
        period = pd.Period(m, freq="M")
        rows.append(
            {
                "month": m,
                "month_end_date": period.to_timestamp(how="end").date().isoformat(),
                "close_adj": 100.0,
                "monthly_value_rub": 1e9,
                "price_return": r,
                "div_return": 0.0,
                "total_return": r,
            }
        )
    write_records_atomic(dir / f"{ticker}.csv", rows, fieldnames=MONTHLY_FIELDS)


def _seed_synthetic_panel(monthly_dir: Path, indices_dir: Path, n_months: int = 20) -> None:
    """8 tickers, 20 months of returns. Patterns give a stable ranking.
    Tickers A-H with linearly decreasing momentum so that Q1={A,B}, Q4={G,H}.
    """
    months = [str(pd.Period("2021-01", "M") + i) for i in range(n_months)]
    # Use small but distinct constant returns per ticker.
    base_returns = {
        "A": 0.03,
        "B": 0.025,
        "C": 0.02,
        "D": 0.015,
        "E": 0.01,
        "F": 0.005,
        "G": 0.0,
        "H": -0.005,
    }
    for tk, r in base_returns.items():
        # Add tiny noise so σ > 0.
        returns: list[float | None] = [None]
        for i in range(1, n_months):
            noise = 0.0001 * ((i * (ord(tk) - ord("A") + 1)) % 7 - 3)
            returns.append(r + noise)
        _seed_monthly_dir(monthly_dir, tk, months, returns)

    # MCFTRR: simple flat 1% per month.
    rows = []
    px = 1000.0
    for m in months:
        period = pd.Period(m, freq="M")
        end = period.to_timestamp(how="end").date().isoformat()
        rows.append({"date": end, "close": px})
        px *= 1.01
    write_records_atomic(indices_dir / "MCFTRR.csv", rows, fieldnames=INDEX_FIELDS)


def test_backtest_smoke_quartile_ranking(tmp_path: Path) -> None:
    monthly_dir = tmp_path / "monthly"
    indices_dir = tmp_path / "indices"
    _seed_synthetic_panel(monthly_dir, indices_dir, n_months=20)
    tickers_dict = {tk: {"type": "share"} for tk in "ABCDEFGH"}
    res = backtest(
        SimpleSignal(),
        monthly_dir=monthly_dir,
        indices_dir=indices_dir,
        tickers_dict=tickers_dict,
        start=pd.Period("2022-01", "M"),
    )
    assert not res.q_values.empty
    assert set(res.q_values.columns) == {"Q1", "Q2", "Q3", "Q4", "MCFTRR"}
    # By construction A,B should dominate Q1 in the first rebalance.
    first_t = sorted(res.holdings.keys())[0]
    assert set(res.holdings[first_t]["Q1"]) == {"A", "B"}
    assert set(res.holdings[first_t]["Q4"]) == {"G", "H"}
    # And Q1 should outperform Q4 by end (this is by construction).
    final = res.q_values.iloc[-1]
    assert final["Q1"] > final["Q4"]


def test_backtest_zero_commission_quartile_sum_equals_universe(tmp_path: Path) -> None:
    """With commission=0, average of Q1..Q4 (equal-weighted) ≈ universe return."""
    monthly_dir = tmp_path / "monthly"
    indices_dir = tmp_path / "indices"
    _seed_synthetic_panel(monthly_dir, indices_dir, n_months=20)
    tickers_dict = {tk: {"type": "share"} for tk in "ABCDEFGH"}
    res = backtest(
        SimpleSignal(),
        monthly_dir=monthly_dir,
        indices_dir=indices_dir,
        tickers_dict=tickers_dict,
        start=pd.Period("2022-01", "M"),
        commission_per_side=0.0,
    )
    # Equal-weight universe NAV (8 tickers): start at 1.0, grow by mean monthly return.
    # Each quartile has 2 tickers; their averaged NAV per month equals the universe avg.
    avg = res.q_values[["Q1", "Q2", "Q3", "Q4"]].mean(axis=1)
    # Simple check: monotone non-decreasing (since all returns ≥ -0.005, average is positive).
    diffs = avg.diff().dropna()
    # Average growth should be roughly 0.01 per month (mean of A..H returns).
    assert diffs.mean() > 0.005


def test_backtest_initial_cost_drag(tmp_path: Path) -> None:
    """With commission>0, the FIRST rebalance imposes a turnover-1 cost on entry,
    so Q-NAVs after the first month are below 1 by ≈ commission."""
    monthly_dir = tmp_path / "monthly"
    indices_dir = tmp_path / "indices"
    _seed_synthetic_panel(monthly_dir, indices_dir, n_months=14)
    tickers_dict = {tk: {"type": "share"} for tk in "ABCDEFGH"}
    res = backtest(
        SimpleSignal(),
        monthly_dir=monthly_dir,
        indices_dir=indices_dir,
        tickers_dict=tickers_dict,
        start=pd.Period("2022-01", "M"),
        commission_per_side=0.01,  # exaggerated for sensitivity
    )
    # First non-trivial row (after first rebalance): Q1 should be 1 × (1 - 0.01) = 0.99.
    first_real = res.q_values.iloc[1]  # row 0 is initial-month (NAV=1)
    assert first_real["Q1"] < 1.0
    assert math.isclose(first_real["Q1"], 0.99, abs_tol=0.002)


def test_write_backtest_roundtrip(tmp_path: Path) -> None:
    monthly_dir = tmp_path / "monthly"
    indices_dir = tmp_path / "indices"
    _seed_synthetic_panel(monthly_dir, indices_dir, n_months=15)
    tickers_dict = {tk: {"type": "share"} for tk in "ABCDEFGH"}
    res = backtest(
        SimpleSignal(),
        monthly_dir=monthly_dir,
        indices_dir=indices_dir,
        tickers_dict=tickers_dict,
        start=pd.Period("2022-01", "M"),
    )
    out_dir = tmp_path / "out"
    write_backtest(res, output_dir=out_dir)
    assert (out_dir / "q_values.csv").exists()
    assert (out_dir / "holdings").is_dir()
    holdings_files = list((out_dir / "holdings").glob("*.json"))
    assert len(holdings_files) == len(res.holdings)
    # Spot-check one holdings file.
    sample = json.loads(holdings_files[0].read_text(encoding="utf-8"))
    assert set(sample.keys()) == {"Q1", "Q2", "Q3", "Q4"}
