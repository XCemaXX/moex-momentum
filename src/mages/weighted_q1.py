"""Mages-tilted Q1 portfolio (task 002, phase 2).

Same Q1 selection as the base momentum strategy, re-weighted toward names the
mages favor. Additive tilt — being named by the mages is an endorsement, so any
mention sits strictly above the un-mentioned floor:

    conviction_i = mi / mean_m   for mentioned tradable shares, else 0
    factor_i     = 1 + λ·conviction_i        (floor = 1 at conviction 0)
    w_i ∝ base_i · factor_i ,  renormalized over the Q1 names

base_i is the equal Q1 weight (constant), so w_i ∝ factor_i. λ=0 reproduces the
equal-weight base Q1; λ grows the premium for mage conviction. mean_m is the mean
weight over the quarter's tradable shares (N = |shares|), so conviction is scale-
invariant and "neutral mention" = 1 regardless of N.

Mechanics mirror the quartile backtest: monthly rebalance, target-to-target
turnover cost, total-return, missing per-ticker return treated as flat.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

from config import COMMISSION_PER_SIDE
from mages.curve import _mcftrr_nav, _turnover
from mages.loader import MagesQuarter
from momentum.universe import load_panel

_LAMBDAS: tuple[float, ...] = (0.0, 0.5, 1.0, 2.0)


def convictions(quarter: MagesQuarter) -> dict[str, float]:
    """ticker -> mi / mean_m = mi · N. weights sum to 1, so mean_m = 1/N.

    N spans all mage shares incl. non-priced ones (task 002 decision): the
    conviction base is the author's book, not our investable subset, so it
    differs slightly from the curve's panel-filtered universe.
    """
    n = quarter.n_shares
    return {tk: w * n for tk, w in quarter.weights.items()}


def additive_tilt(q1: list[str], conv: dict[str, float], lam: float) -> dict[str, float]:
    """Normalized Q1 weights tilted by conviction. Empty Q1 → {}."""
    if not q1:
        return {}
    factors = {tk: 1.0 + lam * conv.get(tk, 0.0) for tk in q1}
    total = sum(factors.values())
    return {tk: f / total for tk, f in factors.items()}


def _conviction_lookup(quarters: list[MagesQuarter]) -> list[tuple[pd.Period, dict[str, float]]]:
    return [(q.period, convictions(q)) for q in sorted(quarters, key=lambda q: q.period)]


def _conv_at(lookup: list[tuple[pd.Period, dict[str, float]]], t: pd.Period) -> dict[str, float]:
    """Active conviction for month t (C1): the latest quarter with period ≤ t."""
    active: dict[str, float] = {}
    for period, conv in lookup:
        if period <= t:
            active = conv
        else:
            break
    return active


def _gross(weights: dict[str, float], month_returns: pd.Series) -> float:
    total = 0.0
    for tk, w in weights.items():
        ri = month_returns.get(tk)
        rv = 0.0 if (ri is None or pd.isna(ri)) else float(ri)
        total += w * rv
    return total


def weighted_q1_nav(
    holdings: dict[str, dict[str, list[str]]],
    returns_panel: pd.DataFrame,
    quarters: list[MagesQuarter],
    lam: float,
    *,
    commission_per_side: float = COMMISSION_PER_SIDE,
    start: pd.Period | None = None,
    end: pd.Period | None = None,
    warm_start: bool = True,
) -> pd.Series:
    """NAV of the λ-tilted Q1 (start = 1.0 the month before the first), Period[M].

    Stepping mirrors the quartile backtest: weights set at close of t-1 earn
    month t, then a rebalance to `holdings[t]` (held over t+1) is charged the
    target-to-target turnover. Conviction for the month being earned is the C1
    active quarter (period ≤ that month).

    warm_start=True (charts): the window opens already holding the tilted Q1, so
    month[0] earns and pays no artificial entry cost — base Q1 is a continuing
    strategy, not a fresh entry. warm_start=False reproduces the backtest's cold
    entry (empty → first month is entry-only), used to validate against q_values.
    """
    if returns_panel.empty:
        return pd.Series(dtype=float)
    lookup = _conviction_lookup(quarters)
    months = returns_panel.index
    if start is not None:
        months = months[months >= start]
    if end is not None:
        months = months[months <= end]
    if len(months) == 0:
        return pd.Series(dtype=float)

    m0 = months[0]
    prev: dict[str, float] = {}
    if warm_start:
        prev = additive_tilt(holdings.get(str(m0 - 1), {}).get("Q1", []), _conv_at(lookup, m0), lam)
    nav = 1.0
    idx: list[pd.Period] = [m0 - 1]
    vals: list[float] = [1.0]
    for t in months:
        if prev:  # weights set at close of t-1 earn month t
            nav *= 1.0 + _gross(prev, returns_panel.loc[t])
        # rebalance at close of t: holdings[t] held over t+1, its conviction
        target = additive_tilt(holdings.get(str(t), {}).get("Q1", []), _conv_at(lookup, t + 1), lam)
        nav *= 1.0 - commission_per_side * _turnover(prev, target)
        prev = target
        idx.append(t)
        vals.append(nav)
    return pd.Series(vals, index=pd.PeriodIndex(idx, freq="M"), dtype=float)


def _lam_label(lam: float) -> str:
    return "Q1 (equal)" if lam == 0.0 else f"λ={lam:g}"


def build_weighted_frame(
    holdings: dict[str, dict[str, list[str]]],
    quarters: list[MagesQuarter],
    *,
    monthly_dir: Path,
    indices_dir: Path,
    lambdas: tuple[float, ...] = _LAMBDAS,
    commission_per_side: float = COMMISSION_PER_SIDE,
) -> pd.DataFrame:
    """DataFrame Period[M]: one NAV column per λ (Q1 equal = λ0) + MCFTRR, over
    the mages window, all rebased to 1.0 at the first quarter month."""
    returns_panel = load_panel(monthly_dir)[0]
    if returns_panel.empty or not quarters:
        return pd.DataFrame()
    start = min(q.period for q in quarters)
    cols: dict[str, pd.Series] = {}
    for lam in lambdas:
        cols[_lam_label(lam)] = weighted_q1_nav(
            holdings,
            returns_panel,
            quarters,
            lam,
            commission_per_side=commission_per_side,
            start=start,
        )
    frame = pd.DataFrame(cols)
    frame["MCFTRR"] = _mcftrr_nav(indices_dir, pd.PeriodIndex(frame.index, freq="M"))
    return frame


def _mages_rows(quarter: MagesQuarter) -> list[list[Any]]:
    """[ticker, name, pct_shares_only] for a quarter's shares, weight DESC."""
    rows = sorted(quarter.shares, key=lambda s: -s["pct_shares_only"])
    return [
        [s["ticker"], s.get("canonical") or s["raw_name"], round(s["pct_shares_only"], 2)]
        for s in rows
    ]


def build_mages_table(
    holdings: dict[str, dict[str, list[str]]],
    quarters: list[MagesQuarter],
    canonical_of: Callable[[str], str],
    *,
    lam: float = 1.0,
) -> dict[str, Any]:
    """Per-month composition for the page table: the λ-weighted Q1 next to the
    quarter's mages list (which repeats within the quarter). Weights in percent,
    each column sorted by weight DESC."""
    if not quarters:
        return {"months": [], "lam": lam, "data": {}}
    lookup = _conviction_lookup(quarters)
    mages_by_period = {q.period: _mages_rows(q) for q in quarters}
    tickers_by_period = {q.period: {s["ticker"] for s in q.shares} for q in quarters}
    first = min(q.period for q in quarters)
    months = [m for m in sorted(pd.Period(m, "M") for m in holdings) if m >= first]

    data: dict[str, dict[str, list[list[Any]]]] = {}
    for t in months:
        active = max((p for p, _ in lookup if p <= t), default=first)
        in_mages = tickers_by_period.get(active, set())
        q1 = holdings.get(str(t - 1), {}).get("Q1", [])
        weights = additive_tilt(q1, _conv_at(lookup, t), lam)
        # Mentioned (Q1 ∩ mages, tilted up) grouped first, then the rest; each
        # by weight DESC. A 4th cell flags membership so the page can rule them off.
        ranked = sorted(weights.items(), key=lambda kv: (kv[0] not in in_mages, -kv[1]))
        weighted: list[list[Any]] = [
            [tk, canonical_of(tk), round(w * 100, 2), tk in in_mages] for tk, w in ranked
        ]
        data[str(t)] = {"weighted": weighted, "mages": mages_by_period.get(active, [])}
    return {"months": [str(m) for m in months], "lam": lam, "data": data}
