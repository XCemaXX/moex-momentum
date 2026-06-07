"""Mages-weighted Q1 (additive λ-tilt) mechanics — task 002, phase 2."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from mages.loader import MagesQuarter, load_quarters
from mages.weighted_q1 import (
    additive_tilt,
    build_mages_table,
    convictions,
    weighted_q1_nav,
)
from momentum.universe import load_panel
from viz.plotly_charts import load_q_values
from viz.site_builder import _load_holdings


def _quarter(
    period: str, weights: dict[str, float], shares: list[dict] | None = None
) -> MagesQuarter:
    return MagesQuarter(
        f"{period}-Q", pd.Period(period, "M"), "url", weights, len(weights), shares=shares or []
    )


def test_convictions_scale_by_n() -> None:
    q = _quarter("2024-01", {"A": 0.5, "B": 0.3, "C": 0.2})
    # conviction = weight · N (N = 3): mean-weight name → 1.
    assert convictions(q) == pytest.approx({"A": 1.5, "B": 0.9, "C": 0.6})


def test_additive_tilt_floor_and_monotone() -> None:
    # B has a small mention (conv 0.5), C is un-mentioned (conv 0 → floor).
    w = additive_tilt(["A", "B", "C"], {"A": 2.0, "B": 0.5}, lam=1.0)
    # factors 3.0 / 1.5 / 1.0, sum 5.5.
    assert w == pytest.approx({"A": 3 / 5.5, "B": 1.5 / 5.5, "C": 1.0 / 5.5})
    # Any mention sits strictly above the un-mentioned floor.
    assert w["B"] > w["C"]
    assert sum(w.values()) == pytest.approx(1.0)


def test_additive_tilt_lambda_zero_is_equal_weight() -> None:
    w = additive_tilt(["A", "B", "C", "D"], {"A": 5.0}, lam=0.0)
    assert w == pytest.approx({t: 0.25 for t in "ABCD"})


def test_weighted_nav_equal_when_no_mages() -> None:
    holdings = {"2023-12": {"Q1": ["A", "B"]}, "2024-01": {"Q1": ["A", "B"]}}
    returns = pd.DataFrame(
        {"A": [0.10], "B": [0.20]}, index=pd.PeriodIndex(["2024-01"], freq="M")
    ).astype(float)
    nav = weighted_q1_nav(
        holdings, returns, [], 0.0, commission_per_side=0.0, start=pd.Period("2024-01", "M")
    )
    # Warm entry holds {A:.5,B:.5}; month return 0.5·0.10+0.5·0.20 = 0.15.
    assert nav.loc[pd.Period("2024-01", "M")] == pytest.approx(1.15)


def test_weighted_nav_applies_conviction_tilt() -> None:
    holdings = {"2023-12": {"Q1": ["A", "B"]}, "2024-01": {"Q1": ["A", "B"]}}
    returns = pd.DataFrame(
        {"A": [0.10], "B": [0.20]}, index=pd.PeriodIndex(["2024-01"], freq="M")
    ).astype(float)
    q = _quarter("2024-01", {"A": 0.75, "B": 0.25})  # conv A=1.5, B=0.5
    nav = weighted_q1_nav(
        holdings, returns, [q], 1.0, commission_per_side=0.0, start=pd.Period("2024-01", "M")
    )
    # factors A=2.5 B=1.5 → weights .625/.375 → return .625·.10 + .375·.20 = .1375.
    assert nav.loc[pd.Period("2024-01", "M")] == pytest.approx(1.1375)


def test_build_mages_table_two_columns() -> None:
    holdings = {"2023-12": {"Q1": ["A", "B", "D"]}, "2024-01": {"Q1": ["A", "C"]}}
    shares = [
        {"ticker": "A", "canonical": "AA", "raw_name": "a", "pct_shares_only": 60.0},
        {"ticker": "B", "canonical": None, "raw_name": "b", "pct_shares_only": 40.0},
    ]
    q = _quarter("2024-01", {"A": 0.6, "B": 0.4}, shares=shares)
    names = {"A": "AA", "B": "BB", "C": "CC", "D": "DD"}
    table = build_mages_table(holdings, [q], lambda t: names[t], lam=1.0)

    assert table["months"] == ["2024-01"]  # only months ≥ first quarter
    d = table["data"]["2024-01"]
    # holdings[2023-12]=[A,B,D], conv A=1.2 B=0.8 D=0 → factors 2.2/1.8/1.0 sum 5.
    # A,B are in mages (flag True) and grouped first; D (not in mages) last.
    assert d["weighted"] == [
        ["A", "AA", 44.0, True],
        ["B", "BB", 36.0, True],
        ["D", "DD", 20.0, False],
    ]
    # Mages column = quarter shares, pct_shares_only DESC; B has no canonical → raw_name.
    assert d["mages"] == [["A", "AA", 60.0], ["B", "b", 40.0]]


def test_cold_lambda_zero_reproduces_base_q1() -> None:
    """λ=0 cold-start over full history must equal the published Q1 NAV exactly —
    the proof the tilt sits on top of the real backtest mechanics."""
    qv_path = Path("data/momentum/curve_fit/q_values.csv")
    holdings_dir = Path("data/momentum/curve_fit/holdings")
    monthly_dir = Path("data/momentum/monthly")
    if not (qv_path.exists() and holdings_dir.exists() and monthly_dir.exists()):
        pytest.skip("backtest output not present")

    holdings = _load_holdings(holdings_dir)
    panel = load_panel(monthly_dir)[0]
    qv = load_q_values(qv_path)
    nav0 = weighted_q1_nav(
        holdings, panel, load_quarters(Path("data/mages")), 0.0, warm_start=False
    )
    common = nav0.index.intersection(qv.index)
    assert len(common) > 100
    assert (nav0.loc[common] - qv["Q1"].loc[common]).abs().max() == pytest.approx(0.0, abs=1e-12)
