"""Top-N fan engine (task 024): ranking, NAV/turnover, concentration nesting."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from momentum.signals import CurveFitSignal
from momentum.topn_fan import (
    monthly_rankings,
    nav_from_selections,
    score_ranking,
    topk_fan,
    turnover_stats,
)


def test_score_ranking_desc_with_ticker_tiebreak() -> None:
    scores = pd.Series({"AAA": 1.0, "BBB": 2.0, "CCC": 2.0, "DDD": float("nan")})
    # 2.0 ties → ticker ASC (BBB before CCC); NaN dropped.
    assert score_ranking(scores) == ["BBB", "CCC", "AAA"]


def test_nav_and_turnover_match_hand_calc() -> None:
    months = pd.period_range("2020-01", "2020-03", freq="M")
    returns = pd.DataFrame(
        {
            "A": [0.0, 0.10, 0.0],
            "B": [0.0, 0.0, 0.20],
        },
        index=months,
    )
    selections = {months[0]: ["A"], months[1]: ["B"]}  # no rebalance in month 3
    curve = nav_from_selections(returns, months, selections, commission=0.001, label="t")

    # init + 3 months.
    assert list(curve.nav.index.astype(str)) == ["2019-12", "2020-01", "2020-02", "2020-03"]
    # entry cost 0.1%; Feb +10% then full swap (turnover 2.0 → 0.2% cost); Mar +20%.
    expected = 1.0 * (1 - 0.001) * 1.10 * (1 - 0.002) * 1.20
    assert curve.nav.iloc[-1] == pytest.approx(expected)

    assert [r.is_entry for r in curve.rebalances] == [True, False]
    feb = curve.rebalances[1]
    assert feb.names_replaced == 1
    assert feb.weight_turnover == pytest.approx(2.0)

    # Steady-state stats exclude the one-off entry.
    stats = turnover_stats(curve.rebalances, commission=0.001)
    assert stats.n_rebalances == 1
    assert stats.mean_names_replaced == 1.0
    assert stats.mean_weight_turnover == pytest.approx(2.0)
    assert stats.annual_cost_pct == pytest.approx(2.0 * 0.001 * 12 * 100)


def _valid_panel() -> tuple[
    tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame], dict[str, dict[str, str]]
]:
    months = pd.period_range("2019-01", "2020-06", freq="M")  # 18 months
    rng = np.random.default_rng(7)
    tickers = [f"T{i}" for i in range(6)]
    returns = pd.DataFrame({t: rng.normal(0.01, 0.05, len(months)) for t in tickers}, index=months)
    # Distinct, constant liquidity: T0 most liquid … T5 least.
    value = pd.DataFrame(
        {t: np.full(len(months), 1e9 - i * 1e8) for i, t in enumerate(tickers)}, index=months
    )
    panels = (returns, returns.copy(), value)
    tickers_dict = {t: {"type": "share"} for t in tickers}
    return panels, tickers_dict


def test_monthly_rankings_skip_short_history() -> None:
    panels, td = _valid_panel()
    start = pd.Period("2019-01", freq="M")
    _months, rankings = monthly_rankings(
        panels, CurveFitSignal(), td, start=start, end=None, top_n=6
    )
    # First 12 months lack the full window → no ranking; later months present.
    assert pd.Period("2019-01", freq="M") not in rankings
    assert rankings  # some months survive
    for rank in rankings.values():
        assert len(rank) == 6  # top_n=6 keeps all eligible names


def test_topk_concentration_is_nested() -> None:
    panels, td = _valid_panel()
    start = pd.Period("2019-01", freq="M")
    fan = topk_fan(panels, CurveFitSignal(), td, start=start, top_n=6, ks=[2, 3], commission=0.0005)
    assert set(fan) == {2, 3}
    _months, rankings = monthly_rankings(
        panels, CurveFitSignal(), td, start=start, end=None, top_n=6
    )
    for rank in rankings.values():
        assert rank[:2] == rank[:3][:2]  # top-2 nests in top-3
    # Both curves run over the same index, no NaN.
    assert not fan[2].nav.isna().any()
    assert len(fan[2].nav) == len(fan[3].nav)
