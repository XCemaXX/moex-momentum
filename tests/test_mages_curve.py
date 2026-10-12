"""Mages equity-curve mechanics (task 002, phase 1)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from mages.curve import (
    _panel_weights,
    flat_positions,
    mages_nav,
    redomicile_predecessors,
    with_predecessors,
)
from mages.loader import MagesQuarter, load_quarters
from tests.conftest import DATA_DIR, Computed
from tickers import load_manual


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


def test_successor_takes_predecessor_return_up_to_redomicile_month() -> None:
    nan = float("nan")
    months = ["2024-05", "2024-06", "2024-07", "2024-08"]
    panel = _returns({"YNDX": [0.01, 0.02, 0.03, nan], "YDEX": [nan, nan, nan, 0.04]}, months)
    out = with_predecessors(panel, {"YDEX": ("YNDX", pd.Period("2024-07", "M"))})
    assert out["YDEX"].tolist() == pytest.approx([0.01, 0.02, 0.03, 0.04])
    assert out["YNDX"].isna().tolist() == [False, False, False, True]


def test_predecessor_return_never_leaks_past_the_redomicile() -> None:
    nan = float("nan")
    panel = _returns({"OLD": [0.01, 0.02], "NEW": [nan, nan]}, ["2025-01", "2025-02"])
    out = with_predecessors(panel, {"NEW": ("OLD", pd.Period("2025-01", "M"))})
    assert out["NEW"].iloc[0] == pytest.approx(0.01)
    assert pd.isna(out["NEW"].iloc[1])


def test_flat_positions_lists_missing_months_per_quarter() -> None:
    nan = float("nan")
    months = ["2024-01", "2024-02", "2024-03", "2024-04"]
    panel = _returns({"A": [0.1, 0.1, 0.1, 0.1], "B": [nan, 0.1, 0.1, nan]}, months)
    q1 = MagesQuarter("2024-Q1", pd.Period("2024-01", "M"), "u", {"A": 0.5, "B": 0.5}, 2, [])
    q2 = MagesQuarter("2024-Q2", pd.Period("2024-04", "M"), "u", {"A": 1.0}, 1, [])
    flat = flat_positions([q1, q2], panel)
    assert [(f.quarter, str(f.month), f.ticker) for f in flat] == [("2024-Q1", "2024-01", "B")]


def test_no_mages_position_is_flat_while_data_exists(computed: Computed) -> None:
    """A position may be booked as 0% only when neither it nor its predecessor
    has a return that month."""
    quarters = load_quarters(DATA_DIR / "mages")
    predecessors = redomicile_predecessors(load_manual(DATA_DIR / "tickers_manual.json"))
    raw = computed.panels[0]
    filled = with_predecessors(raw, predecessors)
    for f in flat_positions(quarters, filled):
        legs = [f.ticker]
        if f.ticker in predecessors and f.month <= predecessors[f.ticker][1]:
            legs.append(predecessors[f.ticker][0])
        for leg in legs:
            assert leg not in raw.columns or pd.isna(raw.at[f.month, leg]), (f, leg)


def test_known_redomicile_gaps_are_bridged(computed: Computed) -> None:
    """2023-Q4..2024-Q2 snapshots name YDEX, RAGR, CNRU before they traded."""
    quarters = load_quarters(DATA_DIR / "mages")
    predecessors = redomicile_predecessors(load_manual(DATA_DIR / "tickers_manual.json"))
    flat = flat_positions(quarters, with_predecessors(computed.panels[0], predecessors))
    early = {f.ticker for f in flat if f.quarter in ("2023-Q4", "2024-Q1", "2024-Q2")}
    # GEMC was halted; FIVE stopped trading 2024-04-03, months before X5 listed.
    assert early <= {"GEMC", "X5"}
