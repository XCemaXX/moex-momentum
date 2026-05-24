"""Momentum signals.

Locked indexing convention (plan §9):
    returns are monthly total returns r_m for months t-11 .. t (12 values).
    r(12-1) = geometric mean of returns[t-11 .. t-1]  (11 values, EXCLUDES t)
    r(6-1)  = geometric mean of returns[t-5  .. t-1]  ( 5 values, EXCLUDES t)
    σ(12)   = sample stdev (ddof=1) of returns[t-11 .. t]  (12 values, INCLUDES t)

The asymmetry — r without t, σ with t — comes directly from the author's methodology:
«в отличие от средней доходности, для подсчета СКО доходность за март
учитывается». Tested in tests/test_momentum_examples.py.

Adding a third signal is a new class implementing `Signal`. Backtest
machinery is signal-agnostic.
"""

from __future__ import annotations

from typing import Protocol, cast

import numpy as np
import pandas as pd

from config import CURVE_FIT_A, CURVE_FIT_B, STDEV_DDOF


def geometric_mean(returns: pd.Series) -> float:
    """((1+r1)(1+r2)...(1+rn))^(1/n) - 1. NaN if any input NaN or n=0."""
    if len(returns) == 0:
        return float("nan")
    if returns.isna().any():
        return float("nan")
    growth = float(cast(float, (1.0 + returns).prod()))
    if growth <= 0:
        return float("nan")
    return float(growth ** (1.0 / len(returns)) - 1.0)


def _slice(returns_panel: pd.DataFrame, start: pd.Period, end: pd.Period) -> pd.DataFrame:
    """Inclusive slice on Period[M] index; missing endpoints → empty."""
    if start not in returns_panel.index or end not in returns_panel.index:
        return returns_panel.iloc[0:0]
    mask = (returns_panel.index >= start) & (returns_panel.index <= end)
    return returns_panel.loc[mask]


def r_skip_month(returns_panel: pd.DataFrame, t: pd.Period, months: int) -> pd.Series:
    """Geometric-mean return over [t-(months-1) .. t-1] — excludes t."""
    start = t - (months - 1)
    end = t - 1
    window = _slice(returns_panel, start, end)
    if len(window) != months - 1:
        return pd.Series(np.nan, index=returns_panel.columns, dtype=float)
    return window.apply(geometric_mean, axis=0)


def sigma_with_t(returns_panel: pd.DataFrame, t: pd.Period, months: int) -> pd.Series:
    """Sample stdev (ddof=1) over [t-(months-1) .. t] — INCLUDES t."""
    start = t - (months - 1)
    end = t
    window = _slice(returns_panel, start, end)
    if len(window) != months:
        return pd.Series(np.nan, index=returns_panel.columns, dtype=float)
    return window.std(axis=0, ddof=STDEV_DDOF)


class Signal(Protocol):
    name: str

    def compute(self, returns_panel: pd.DataFrame, t: pd.Period) -> pd.Series: ...


class SimpleSignal:
    """r(12-1) / σ(12)."""

    name = "simple"

    def compute(self, returns_panel: pd.DataFrame, t: pd.Period) -> pd.Series:
        r12 = r_skip_month(returns_panel, t, 12)
        sd = sigma_with_t(returns_panel, t, 12)
        return r12 / sd


class CurveFitSignal:
    """(a·r(12-1) + b·r(6-1)) / σ(12). Defaults: a=0.9, b=0.1 (author's curve-fit)."""

    name = "curve_fit"

    def __init__(self, a: float = CURVE_FIT_A, b: float = CURVE_FIT_B) -> None:
        self.a = a
        self.b = b

    def compute(self, returns_panel: pd.DataFrame, t: pd.Period) -> pd.Series:
        r12 = r_skip_month(returns_panel, t, 12)
        r6 = r_skip_month(returns_panel, t, 6)
        sd = sigma_with_t(returns_panel, t, 12)
        return (self.a * r12 + self.b * r6) / sd


SIGNALS: dict[str, Signal] = {
    "simple": SimpleSignal(),
    "curve_fit": CurveFitSignal(),
}
