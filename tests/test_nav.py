"""Shared NAV primitives — turnover cost and gross return."""

from __future__ import annotations

import math

import pandas as pd

from momentum.nav import gross_return, turnover


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
        gross_return(w, r, period=pd.Period("2022-01", "M"), label="Q1"),
        0.0,
        abs_tol=1e-12,
    )


def test_gross_return_missing_ticker_treated_as_zero() -> None:
    w = {"A": 0.5, "B": 0.5}
    r = pd.Series({"A": 0.20})  # B missing
    out = gross_return(w, r, period=pd.Period("2022-01", "M"), label="Q1")
    # B contributes 0 → return = 0.5 × 0.20 + 0.5 × 0 = 0.10
    assert math.isclose(out, 0.10, abs_tol=1e-12)


def test_gross_return_collects_misses_instead_of_warning() -> None:
    misses: list[tuple[str, str, str]] = []
    gross_return(
        {"A": 1.0},
        pd.Series({"B": 0.1}),
        period=pd.Period("2022-01", "M"),
        label="λ=0.5",
        misses=misses,
    )
    assert misses == [("2022-01", "A", "λ=0.5")]
