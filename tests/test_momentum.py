"""Unit tests for momentum signals — isolated from disk and backtest engine.

Covers:
    - geometric_mean correctness
    - r(12-1) / r(6-1) skip-month indexing
    - σ(12) inclusion of month t and ddof=1
    - CurveFit / Simple signal composition
    - the locked asymmetry: r excludes t, σ includes t
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from momentum.signals import (
    CurveFitSignal,
    SimpleSignal,
    geometric_mean,
    r_skip_month,
    sigma_with_t,
)


def _panel(returns_by_ticker: dict[str, list[float]], start: str) -> pd.DataFrame:
    idx = pd.period_range(
        start=start, periods=len(next(iter(returns_by_ticker.values()))), freq="M"
    )
    return pd.DataFrame(returns_by_ticker, index=idx)


def test_geometric_mean_known_values() -> None:
    # (1.10 × 1.20 × 0.90)^(1/3) - 1
    s = pd.Series([0.10, 0.20, -0.10])
    expected = (1.1 * 1.2 * 0.9) ** (1 / 3) - 1
    assert math.isclose(geometric_mean(s), expected, abs_tol=1e-12)


def test_geometric_mean_nan_input_nan_output() -> None:
    assert math.isnan(geometric_mean(pd.Series([0.1, float("nan"), 0.05])))


def test_geometric_mean_empty_is_nan() -> None:
    assert math.isnan(geometric_mean(pd.Series([], dtype=float)))


def test_r_skip_month_excludes_t() -> None:
    # 12 returns ending at 2022-02; r(12-1) on month t=2022-02 should use only
    # returns from 2021-03 .. 2022-01 (11 values, EXCLUDES Feb).
    returns = [0.10] * 12
    panel = _panel({"A": returns}, start="2021-03")
    t = pd.Period("2022-02", freq="M")
    r12 = r_skip_month(panel, t, 12)
    assert math.isclose(r12["A"], 0.10, abs_tol=1e-12)
    # If we change t's return to something extreme, r12 stays the same.
    returns[-1] = 5.0
    panel2 = _panel({"A": returns}, start="2021-03")
    assert math.isclose(r_skip_month(panel2, t, 12)["A"], 0.10, abs_tol=1e-12)


def test_r6_uses_5_returns() -> None:
    returns = list(range(12))
    returns_floats = [float(r) / 100 for r in returns]
    panel = _panel({"A": returns_floats}, start="2021-03")
    t = pd.Period("2022-02", freq="M")
    r6 = r_skip_month(panel, t, 6)
    # window = months [t-5..t-1] = 2021-09..2022-01 = returns at positions 6..10 (0-indexed)
    expected = geometric_mean(pd.Series(returns_floats[6:11]))
    assert math.isclose(r6["A"], expected, abs_tol=1e-12)


def test_sigma_includes_t_with_ddof1() -> None:
    returns = [0.1, 0.2, 0.3, -0.1, 0.0, 0.05, 0.04, 0.03, 0.02, 0.01, 0.0, 0.5]
    panel = _panel({"A": returns}, start="2021-03")
    t = pd.Period("2022-02", freq="M")
    sd = sigma_with_t(panel, t, 12)
    expected = pd.Series(returns).std(ddof=1)
    assert math.isclose(sd["A"], expected, abs_tol=1e-12)
    # Verify INCLUSION: dropping t (return 0.5) gives a different stdev.
    sd_without_t = pd.Series(returns[:-1]).std(ddof=1)
    assert not math.isclose(sd["A"], sd_without_t, abs_tol=1e-6)


def test_asymmetry_r_unaffected_sigma_affected_by_t() -> None:
    """Locked asymmetry from the author's worked example: changing return at t
    changes σ(12) but not r(12-1)."""
    returns_a = [0.05] * 12
    returns_b = list(returns_a)
    returns_b[-1] = 0.30  # change only t
    panel_a = _panel({"A": returns_a}, start="2021-03")
    panel_b = _panel({"A": returns_b}, start="2021-03")
    t = pd.Period("2022-02", freq="M")
    assert math.isclose(
        r_skip_month(panel_a, t, 12)["A"],
        r_skip_month(panel_b, t, 12)["A"],
        abs_tol=1e-12,
    )
    sa = sigma_with_t(panel_a, t, 12)["A"]
    sb = sigma_with_t(panel_b, t, 12)["A"]
    assert not math.isclose(sa, sb, abs_tol=1e-6)


def test_simple_signal_known_value() -> None:
    returns = [0.05] * 12
    panel = _panel({"A": returns}, start="2021-03")
    t = pd.Period("2022-02", freq="M")
    score = SimpleSignal().compute(panel, t)["A"]
    # All identical → σ ≈ 0 → score explodes (in floating point, not necessarily inf).
    assert abs(score) > 1e10


def test_curve_fit_signal_decomposes_correctly() -> None:
    returns = [0.01, 0.02, -0.01, 0.03, 0.02, 0.05, 0.04, 0.03, 0.02, 0.01, 0.0, 0.06]
    panel = _panel({"A": returns}, start="2021-03")
    t = pd.Period("2022-02", freq="M")
    r12 = r_skip_month(panel, t, 12)["A"]
    r6 = r_skip_month(panel, t, 6)["A"]
    sd = sigma_with_t(panel, t, 12)["A"]
    expected = (0.9 * r12 + 0.1 * r6) / sd
    actual = CurveFitSignal(a=0.9, b=0.1).compute(panel, t)["A"]
    assert math.isclose(actual, expected, abs_tol=1e-12)


def test_insufficient_window_returns_nan() -> None:
    returns = [0.05] * 5
    panel = _panel({"A": returns}, start="2021-10")
    t = pd.Period("2022-02", freq="M")
    assert np.isnan(r_skip_month(panel, t, 12)["A"])
    assert np.isnan(sigma_with_t(panel, t, 12)["A"])


def test_panel_with_nan_in_window_yields_nan_score() -> None:
    returns = [0.05, float("nan"), 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05]
    panel = _panel({"A": returns}, start="2021-03")
    t = pd.Period("2022-02", freq="M")
    # NaN at t-10 falls inside r12 window → r12 = NaN → signal = NaN.
    score = SimpleSignal().compute(panel, t)["A"]
    assert np.isnan(score)


@pytest.fixture
def vsmo_returns_from_info_txt() -> list[float]:
    """11 monthly returns for VSMO Apr-2021 .. Feb-2022, computed from the
    12 closes in the author's published worked example (its r(12-1) = 4.6458%).
    """
    closes = [26700, 24140, 27040, 29300, 30620, 31220, 34300, 37380, 44000, 46900, 47500, 44000]
    return [closes[i + 1] / closes[i] - 1.0 for i in range(11)]


def test_vsmo_regression_anchor(vsmo_returns_from_info_txt: list[float]) -> None:
    """VSMO 2022-03 simple-r(12-1) = 4.6458% ± 0.05%.

    Plan §572 / SPEC §90: regression anchor for the simple momentum signal,
    computed directly from the author's 12 monthly closes.
    """
    returns = vsmo_returns_from_info_txt
    panel = _panel({"VSMO": returns + [float("nan")]}, start="2021-04")
    # t = 2022-03; r(12-1) needs returns at t-11..t-1 = 2021-04..2022-02, i.e. our 11 returns.
    t = pd.Period("2022-03", freq="M")
    r12 = r_skip_month(panel, t, 12)["VSMO"]
    assert math.isclose(r12, 0.046458, abs_tol=0.0005)
