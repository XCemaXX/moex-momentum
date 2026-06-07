"""Q1 top15 concentration on the home page — task 026.

The home charts compute top15 inline (scores.csv + monthly panel) instead of
reading the research-only concentration CSV. The key invariant: that inline NAV
must equal the `k15` column the task-024 fan would produce.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import tickers as t_mod
from config import (
    ANALYSIS_START_DATE,
    COMMISSION_PER_SIDE,
    TOP_K_CONCENTRATION,
    UNIVERSE_TOP_N_LIQUID,
)
from momentum.signals import CurveFitSignal
from momentum.topn_fan import topk_fan
from momentum.universe import load_panel
from viz.plotly_charts import (
    Q1_TOP15_COLOR,
    _plot_strategy_vs_mcftrr,
    plot_q1_q4_dynamics,
)
from viz.site_builder import _env, _load_scores, _q1top15_nav, _top15_assets


def _sample_q_values() -> pd.DataFrame:
    idx = pd.PeriodIndex(["2024-01", "2024-02", "2024-03"], freq="M")
    return pd.DataFrame(
        {
            "Q1": [1.0, 1.1, 1.2],
            "Q2": [1.0, 1.05, 1.1],
            "Q3": [1.0, 1.02, 1.04],
            "Q4": [1.0, 0.99, 0.98],
            "MCFTRR": [1.0, 1.03, 1.06],
        },
        index=idx,
    ).astype(float)


def test_dynamics_adds_extra_line() -> None:
    q = _sample_q_values()
    base = plot_q1_q4_dynamics(q)
    extra = pd.Series([1.0, 1.15, 1.3], index=q.index)
    fig = plot_q1_q4_dynamics(q, extra_series=[("Q1 top15", extra, Q1_TOP15_COLOR)])
    assert len(fig.data) == len(base.data) + 1
    top15 = fig.data[-1]
    assert top15.name == "Q1 top15"
    assert top15.line.color == Q1_TOP15_COLOR
    assert top15.line.dash == "solid"  # strategy, not benchmark


def test_strategy_vs_mcftrr_labels_follow_name() -> None:
    q = _sample_q_values()
    frame = pd.DataFrame({"Q1 top15": q["Q1"], "MCFTRR": q["MCFTRR"]})
    fig = _plot_strategy_vs_mcftrr(frame, "Q1 top15", strat_name="Q1 top15", title="t")
    names = [tr.name for tr in fig.data]
    assert "Q1 top15 return" in names
    assert "Q1 top15 > MCFTRR" in names
    assert "Q1 top15 < MCFTRR" in names
    assert "MCFTRR return" in names


def test_top15_assets_skips_without_scores() -> None:
    q = _sample_q_values()
    # No scores or no panel → no line, no embed (pre-task-025 output stays valid).
    assert _top15_assets({}, None, q, "Q1 top15") == (None, "")
    assert _top15_assets({"2024-01": {"A": 1.0}}, None, q, "Q1 top15") == (None, "")


def test_chart_template_second_main_guard() -> None:
    tmpl = _env().get_template("chart.html")
    base = {"title": "t", "nav_links": [], "current_href": "x", "chart_html": "<div>A</div>"}
    one = tmpl.render(**base, chart_html_2="")
    two = tmpl.render(**base, chart_html_2="<div>B</div>")
    assert one.count('<main class="full">') == 1
    assert two.count('<main class="full">') == 2


def test_inline_top15_matches_topn_fan() -> None:
    """Inline top15 (from scores.csv) == the task-024 fan's k15 (recomputed from
    panels + signal) on the shared window — proves no research CSV is needed."""
    monthly_dir = Path("data/momentum/monthly")
    scores_path = Path("data/momentum/curve_fit/scores.csv")
    tickers_file = Path("data/tickers.json")
    if not (monthly_dir.exists() and scores_path.exists() and tickers_file.exists()):
        pytest.skip("backtest output not present")

    k = TOP_K_CONCENTRATION
    inline = _q1top15_nav(_load_scores(scores_path), monthly_dir, k=k)
    assert inline is not None

    panels = load_panel(monthly_dir)
    fan = topk_fan(
        panels,
        CurveFitSignal(),
        t_mod.load(tickers_file),
        start=pd.Period(ANALYSIS_START_DATE, freq="M"),
        top_n=UNIVERSE_TOP_N_LIQUID,
        ks=[k],
        commission=COMMISSION_PER_SIDE,
    )
    ref = fan[k].nav
    common = inline.index.intersection(ref.index)
    assert len(common) > 100
    assert (inline.loc[common] - ref.loc[common]).abs().max() == pytest.approx(0.0, abs=1e-9)
