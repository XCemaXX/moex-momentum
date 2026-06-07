"""Mages equity-curve mechanics (task 002, phase 1)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from mages.curve import _panel_weights, _turnover, mages_nav
from mages.loader import MagesQuarter, load_quarters


def _returns(data: dict[str, list[float]], months: list[str]) -> pd.DataFrame:
    return pd.DataFrame(data, index=pd.PeriodIndex(months, freq="M")).astype(float)


def test_mages_nav_drift_no_commission() -> None:
    returns = _returns({"A": [0.10, 0.0], "B": [0.20, -0.10]}, ["2024-01", "2024-02"])
    q = MagesQuarter(
        "2024-Q1", pd.Period("2024-01", "M"), "url", {"A": 0.6, "B": 0.4}, 2, shares=[]
    )
    nav = mages_nav([q], returns, commission_per_side=0.0)

    # Init month is the month before the first quarter, NAV = 1.0.
    assert nav.loc[pd.Period("2023-12", "M")] == 1.0
    # Month 1: 0.6·1.10 + 0.4·1.20 = 1.14.
    assert nav.loc[pd.Period("2024-01", "M")] == pytest.approx(1.14)
    # Month 2 (drifted weights, no rebalance): 0.66·1.0 + 0.48·0.9 = 1.092.
    assert nav.loc[pd.Period("2024-02", "M")] == pytest.approx(1.092)


def test_mages_nav_charges_entry_commission() -> None:
    returns = _returns({"A": [0.10], "B": [0.20]}, ["2024-01"])
    q = MagesQuarter(
        "2024-Q1", pd.Period("2024-01", "M"), "url", {"A": 0.6, "B": 0.4}, 2, shares=[]
    )
    nav = mages_nav([q], returns, commission_per_side=0.0005)
    # Entry from empty = turnover 1.0 → cost 0.0005, then earn 1.14.
    assert nav.loc[pd.Period("2024-01", "M")] == pytest.approx(0.9995 * 1.14)


def test_mages_nav_missing_return_is_flat() -> None:
    returns = _returns({"A": [0.10, 0.05], "B": [0.20, float("nan")]}, ["2024-01", "2024-02"])
    q = MagesQuarter(
        "2024-Q1", pd.Period("2024-01", "M"), "url", {"A": 0.6, "B": 0.4}, 2, shares=[]
    )
    nav = mages_nav([q], returns, commission_per_side=0.0)
    # Month 2: A grows (0.66·1.05), B flat (0.48·1.0) → 1.143.
    assert nav.loc[pd.Period("2024-02", "M")] == pytest.approx(0.66 * 1.05 + 0.48 * 1.0)


def test_panel_weights_drops_unpriced_and_renormalizes() -> None:
    w = _panel_weights({"A": 0.5, "B": 0.3, "C": 0.2}, {"A", "B"})
    assert w == pytest.approx({"A": 0.625, "B": 0.375})
    assert sum(w.values()) == pytest.approx(1.0)


def test_turnover_counts_both_sides() -> None:
    assert _turnover({"A": 0.6, "B": 0.4}, {"A": 0.5, "C": 0.5}) == pytest.approx(1.0)


def test_load_quarters_weights_sum_to_one(tmp_path: Path) -> None:
    doc = {
        "quarter": "2024-Q1",
        "period": "2024-01",
        "source": "url",
        "shares": [
            {"ticker": "A", "canonical": "a", "raw_name": "a", "pct": 30, "pct_shares_only": 60},
            {"ticker": "B", "canonical": "b", "raw_name": "b", "pct": 20, "pct_shares_only": 40},
        ],
        "other": [{"ticker": "Z", "raw_name": "z", "pct": 5, "type": "otc"}],
    }
    (tmp_path / "2024-Q1.json").write_text(json.dumps(doc), encoding="utf-8")
    quarters = load_quarters(tmp_path)
    assert len(quarters) == 1
    q = quarters[0]
    assert q.n_shares == 2
    assert q.weights == pytest.approx({"A": 0.6, "B": 0.4})
    assert q.period == pd.Period("2024-01", "M")
