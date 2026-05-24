"""Pending-inclusion block tests (task 008). Display-only, additive."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from momentum.backtest import BacktestResult, quartile_split, write_backtest
from momentum.pending import (
    PendingEntry,
    _candidate_score,
    _would_be_q,
    compute_month_pending,
)
from momentum.signals import SimpleSignal

Spec = tuple[str, str, list[float], float]


def _panels(specs: list[Spec]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build (returns, close, value) panels. Each spec lists a ticker, its first
    listed month, its monthly returns, and a flat monthly turnover. Closes span
    [start .. start+len(rets)] (listing month return is NaN)."""
    months = pd.period_range("2019-06", periods=40, freq="M")
    rcols: dict[str, pd.Series] = {}
    ccols: dict[str, pd.Series] = {}
    vcols: dict[str, pd.Series] = {}
    for tk, start, rets, value in specs:
        s0 = pd.Period(start, "M")
        closes = {s0 + i: 100.0 for i in range(len(rets) + 1)}
        values = {s0 + i: value for i in range(len(rets) + 1)}
        returns = {s0 + 1 + i: r for i, r in enumerate(rets)}
        rcols[tk] = pd.Series(returns, dtype=float).reindex(months)
        ccols[tk] = pd.Series(closes, dtype=float).reindex(months)
        vcols[tk] = pd.Series(values, dtype=float).reindex(months)
    return pd.DataFrame(rcols), pd.DataFrame(ccols), pd.DataFrame(vcols)


def test_would_be_q_boundaries() -> None:
    floors = (3.0, 2.0, 1.0)  # q1_min, q2_min, q3_min
    assert _would_be_q(3.5, floors) == "Q1"
    assert _would_be_q(3.0, floors) == "Q1"
    assert _would_be_q(2.5, floors) == "Q2"
    assert _would_be_q(1.5, floors) == "Q3"
    assert _would_be_q(0.5, floors) == "Q4"


def test_candidate_score_matches_simple_on_full_history() -> None:
    """r_L/σ_L over a full 12-return window == production SimpleSignal r(12-1)/σ(12)."""
    rets = [0.02, -0.01, 0.03, 0.0, 0.05, -0.02, 0.01, 0.04, -0.03, 0.02, 0.01, 0.06]
    rp, _, _ = _panels([("X", "2020-01", rets, 1e8)])
    first = pd.Period("2020-01", "M")
    t = first + 12  # 2021-01: 13 closes, 12 returns
    scored = _candidate_score(rp["X"], first, t)
    assert scored is not None
    score, n = scored
    simple = float(SimpleSignal().compute(rp[["X"]], t)["X"])
    assert n == 11
    assert score == pytest.approx(simple)


def _placement_inputs() -> tuple[pd.Series, dict[str, list[str]]]:
    scores = pd.Series({"U1": 3.0, "U2": 2.0, "U3": 1.0, "U4": 0.0})
    return scores, quartile_split(scores)


def test_pending_early_below_min_age() -> None:
    rp, cp, vp = _panels([("YOUNG", "2021-01", [0.05, 0.04, 0.03], 1e9)])
    scores, quartiles = _placement_inputs()
    t = pd.Period("2021-01", "M") + 3  # age 3 < 6
    out = compute_month_pending(
        t,
        returns_panel=rp,
        close_panel=cp,
        value_panel=vp,
        tickers_dict={"YOUNG": {"type": "share"}},
        universe=["U1", "U2", "U3", "U4"],
        scores=scores,
        quartiles=quartiles,
        liquidity_floor=1e6,
    )
    assert len(out) == 1
    assert out[0].ticker == "YOUNG"
    assert out[0].age == 3
    assert out[0].status == "early"
    assert out[0].would_be_q is None


def test_pending_estimated_assigns_quartile() -> None:
    # Varied returns → σ > 0 → a score exists (constant returns would be unscoreable).
    rp, cp, vp = _panels(
        [("MID", "2021-01", [0.05, -0.02, 0.04, 0.01, 0.06, -0.01, 0.03, 0.02], 1e9)]
    )
    scores, quartiles = _placement_inputs()
    t = pd.Period("2021-01", "M") + 8  # age 8 ≥ 6
    out = compute_month_pending(
        t,
        returns_panel=rp,
        close_panel=cp,
        value_panel=vp,
        tickers_dict={"MID": {"type": "share"}},
        universe=["U1", "U2", "U3", "U4"],
        scores=scores,
        quartiles=quartiles,
        liquidity_floor=1e6,
    )
    assert len(out) == 1
    e = out[0]
    assert e.status == "estimated"
    assert e.age == 8
    assert e.n == 7  # r-window = age-1
    assert e.would_be_q in {"Q1", "Q2", "Q3", "Q4"}
    assert e.score is not None


def test_pending_excludes_illiquid() -> None:
    rp, cp, vp = _panels([("THIN", "2021-01", [0.05] * 8, 1e5)])
    scores, quartiles = _placement_inputs()
    t = pd.Period("2021-01", "M") + 8
    out = compute_month_pending(
        t,
        returns_panel=rp,
        close_panel=cp,
        value_panel=vp,
        tickers_dict={"THIN": {"type": "share"}},
        universe=["U1", "U2", "U3", "U4"],
        scores=scores,
        quartiles=quartiles,
        liquidity_floor=1e6,  # THIN's 1e5 turnover is below the floor
    )
    assert out == []


def test_pending_excludes_qable_ticker() -> None:
    """age ≥ 12 → q is computed → not a pending candidate."""
    rp, cp, vp = _panels([("OLD", "2021-01", [0.05] * 13, 1e9)])
    scores, quartiles = _placement_inputs()
    t = pd.Period("2021-01", "M") + 13  # age 13
    out = compute_month_pending(
        t,
        returns_panel=rp,
        close_panel=cp,
        value_panel=vp,
        tickers_dict={"OLD": {"type": "share"}},
        universe=["U1", "U2", "U3", "U4"],
        scores=scores,
        quartiles=quartiles,
        liquidity_floor=1e6,
    )
    assert out == []


def test_pending_no_floor_returns_empty() -> None:
    rp, cp, vp = _panels([("YOUNG", "2021-01", [0.05] * 8, 1e9)])
    scores, quartiles = _placement_inputs()
    t = pd.Period("2021-01", "M") + 8
    out = compute_month_pending(
        t,
        returns_panel=rp,
        close_panel=cp,
        value_panel=vp,
        tickers_dict={"YOUNG": {"type": "share"}},
        universe=["U1", "U2", "U3", "U4"],
        scores=scores,
        quartiles=quartiles,
        liquidity_floor=None,
    )
    assert out == []


def test_pending_excludes_at_liquidity_floor() -> None:
    """Median turnover exactly at the floor is excluded (strict 'above')."""
    rp, cp, vp = _panels([("EDGE", "2021-01", [0.05] * 8, 1e6)])
    scores, quartiles = _placement_inputs()
    t = pd.Period("2021-01", "M") + 8
    out = compute_month_pending(
        t,
        returns_panel=rp,
        close_panel=cp,
        value_panel=vp,
        tickers_dict={"EDGE": {"type": "share"}},
        universe=["U1", "U2", "U3", "U4"],
        scores=scores,
        quartiles=quartiles,
        liquidity_floor=1e6,  # med == floor → excluded
    )
    assert out == []


def test_pending_unscoreable_falls_back_to_early() -> None:
    """age ≥ 6 but σ == 0 (flat returns) → no score → 'early', not 'estimated'."""
    rp, cp, vp = _panels([("FLAT", "2021-01", [0.03] * 8, 1e9)])
    scores, quartiles = _placement_inputs()
    t = pd.Period("2021-01", "M") + 8
    out = compute_month_pending(
        t,
        returns_panel=rp,
        close_panel=cp,
        value_panel=vp,
        tickers_dict={"FLAT": {"type": "share"}},
        universe=["U1", "U2", "U3", "U4"],
        scores=scores,
        quartiles=quartiles,
        liquidity_floor=1e6,
    )
    assert len(out) == 1
    assert out[0].status == "early"
    assert out[0].would_be_q is None


def test_pending_degenerate_quartiles_fall_back_to_early() -> None:
    """An empty quartile → no floors → age ≥ 6 candidate degrades to 'early'."""
    rp, cp, vp = _panels(
        [("MID", "2021-01", [0.05, -0.02, 0.04, 0.01, 0.06, -0.01, 0.03, 0.02], 1e9)]
    )
    scores = pd.Series({"U2": 2.0, "U3": 1.0, "U4": 0.0})
    quartiles = {"Q1": [], "Q2": ["U2"], "Q3": ["U3"], "Q4": ["U4"]}
    t = pd.Period("2021-01", "M") + 8
    out = compute_month_pending(
        t,
        returns_panel=rp,
        close_panel=cp,
        value_panel=vp,
        tickers_dict={"MID": {"type": "share"}},
        universe=["U2", "U3", "U4"],
        scores=scores,
        quartiles=quartiles,
        liquidity_floor=1e6,
    )
    assert len(out) == 1
    assert out[0].status == "early"
    assert out[0].would_be_q is None


def test_pending_gap_restarts_age() -> None:
    """A close gap restarts the age clock (mirrors the universe rule). By absolute
    first listing this name would be age 16 (skipped); by the current run it is 9."""
    months = pd.period_range("2020-01", "2021-05", freq="M")
    halt = pd.Period("2020-07", "M")
    traded = [m for m in months if m != halt]
    closes = pd.Series({m: 100.0 for m in traded}, dtype=float).reindex(months)
    values = pd.Series({m: 1e9 for m in traded}, dtype=float).reindex(months)
    vary = [0.05, -0.02, 0.04, 0.01, 0.06, -0.01, 0.03, 0.02, 0.05, -0.03, 0.04, 0.02]
    rets: dict[pd.Period, float] = {}
    k = 0
    for m in traded:
        if (m - 1) in traded:  # return needs the prior month's close
            rets[m] = vary[k % len(vary)]
            k += 1
    rp = pd.DataFrame({"GAP": pd.Series(rets, dtype=float).reindex(months)})
    cp = pd.DataFrame({"GAP": closes})
    vp = pd.DataFrame({"GAP": values})
    scores, quartiles = _placement_inputs()
    out = compute_month_pending(
        pd.Period("2021-05", "M"),
        returns_panel=rp,
        close_panel=cp,
        value_panel=vp,
        tickers_dict={"GAP": {"type": "share"}},
        universe=["U1", "U2", "U3", "U4"],
        scores=scores,
        quartiles=quartiles,
        liquidity_floor=1e6,
    )
    assert len(out) == 1
    assert out[0].ticker == "GAP"
    assert out[0].age == 9  # run start 2020-08 → 9 months to 2021-05
    assert out[0].status == "estimated"
    assert out[0].n == 8  # returns 2020-09..2021-04 (2020-08's is NaN, excludes t)


def test_write_pending_gated(tmp_path: Path) -> None:
    result = BacktestResult(
        q_values=pd.DataFrame({"Q1": [1.0]}, index=pd.Index(["2021-01"], name="month")),
        pending={pd.Period("2021-01", "M"): [PendingEntry("YOUNG", 3, "early")]},
    )
    # Default: no pending.json.
    write_backtest(result, output_dir=tmp_path / "off")
    assert not (tmp_path / "off" / "pending.json").exists()
    # Gated on: pending.json written.
    write_backtest(result, output_dir=tmp_path / "on", write_pending=True)
    assert (tmp_path / "on" / "pending.json").exists()
