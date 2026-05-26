"""Top-N fan engine — research support for task 024.

`topn` is a liquidity gate, not a formula term: a stock's momentum score depends
only on its own return history (see signals.py), so it is identical in any
universe. Two fans follow from that:

- Approach 1 (universe width): vary `universe_top_n`. Run via the normal
  `backtest` — the held set is the quartile Q1. Shrinking topn raises the
  liquidity floor AND shrinks Q1 together (confounded by design).
- Approach 2 (concentration): fix the top-100 universe, hold the top-K names by
  score. This module's `topk_fan` builds those curves — the score-ranking is
  computed once per month and sliced per K. K=25 nests inside Q1; K>25 dips into
  Q2 (quartiles are irrelevant here, it is just "hold the K strongest names").

Equal-weight throughout. NAV/turnover mechanics mirror `backtest` exactly.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from momentum.backtest import gross_return, turnover
from momentum.signals import Signal
from momentum.universe import universe_at
from tickers import TickersDict

Panels = tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]


def score_ranking(scores: pd.Series) -> list[str]:
    """Tickers ranked by score DESC, ties broken by ticker ASC — the same key as
    `quartile_split`, so a top-K slice nests inside Q1 for K <= |Q1|."""
    s = scores.dropna()
    pairs = sorted(s.items(), key=lambda kv: (-float(kv[1]), str(kv[0])))
    return [str(tk) for tk, _ in pairs]


def monthly_rankings(
    panels: Panels,
    signal: Signal,
    tickers_dict: TickersDict,
    *,
    start: pd.Period,
    end: pd.Period | None,
    top_n: int,
) -> tuple[pd.Index, dict[pd.Period, list[str]]]:
    """Per-month score-ranking of the top-`top_n` liquid universe.

    Returns (months iterated, {month: tickers DESC by score}). Months with an
    empty universe (too little history) are simply absent from the dict.
    """
    returns_panel, _close, value_panel = panels
    months = returns_panel.index
    months = months[months >= start]
    if end is not None:
        months = months[months <= end]
    rankings: dict[pd.Period, list[str]] = {}
    for t in months:
        universe = universe_at(t, returns_panel, tickers_dict, value_panel=value_panel, top_n=top_n)
        if not universe:
            continue
        scores = signal.compute(returns_panel.loc[:, universe], t)
        rankings[t] = score_ranking(scores)
    return months, rankings


@dataclass
class Rebalance:
    month: pd.Period
    weight_turnover: float  # Σ|Δw| ∈ [0, 2]
    names_replaced: int  # |new \ old|
    size: int  # held count this month
    is_entry: bool  # first rebalance from empty — one-off, excluded from means


@dataclass
class FanCurve:
    nav: pd.Series  # index Period[M], leading row = 1.0
    rebalances: list[Rebalance]


def nav_from_selections(
    returns_panel: pd.DataFrame,
    months: pd.Index,
    selections: dict[pd.Period, list[str]],
    *,
    commission: float,
    label: str,
) -> FanCurve:
    """Equal-weight NAV from a timeline of held sets, mirroring `backtest`:
    holdings chosen at close of t earn month-(t+1) return; rebalance cost is
    `commission · Σ|Δw|` charged at t."""
    nav = 1.0
    prev_w: dict[str, float] = {}
    idx: list[pd.Period] = [months[0] - 1]
    vals: list[float] = [1.0]
    rebalances: list[Rebalance] = []
    for t in months:
        if prev_w:
            nav *= 1.0 + gross_return(prev_w, returns_panel.loc[t], period=t, quartile=label)
        sel = selections.get(t)
        if sel:
            w = 1.0 / len(sel)
            new_w = {tk: w for tk in sel}
            to = turnover(prev_w, new_w)
            replaced = len(set(new_w) - set(prev_w))
            nav *= 1.0 - commission * to
            rebalances.append(Rebalance(t, to, replaced, len(sel), is_entry=not prev_w))
            prev_w = new_w
        idx.append(t)
        vals.append(nav)
    nav_series = pd.Series(vals, index=pd.PeriodIndex(idx, freq="M"), name=label)
    return FanCurve(nav=nav_series, rebalances=rebalances)


def topk_fan(
    panels: Panels,
    signal: Signal,
    tickers_dict: TickersDict,
    *,
    start: pd.Period,
    end: pd.Period | None = None,
    top_n: int,
    ks: list[int],
    commission: float,
) -> dict[int, FanCurve]:
    """Concentration fan (approach 2): one curve per K, all from the same
    top-`top_n` universe and a single per-month ranking."""
    returns_panel = panels[0]
    months, rankings = monthly_rankings(
        panels, signal, tickers_dict, start=start, end=end, top_n=top_n
    )
    out: dict[int, FanCurve] = {}
    for k in ks:
        selections = {t: rank[:k] for t, rank in rankings.items()}
        out[k] = nav_from_selections(
            returns_panel, months, selections, commission=commission, label=f"k{k}"
        )
    return out


@dataclass
class TurnoverStats:
    mean_names_replaced: float  # steady-state, excludes the one-off entry
    mean_pct_replaced: float  # names_replaced / size
    mean_weight_turnover: float  # Σ|Δw| per month
    annual_cost_pct: float  # mean monthly turnover · commission · 12, in %
    n_rebalances: int


def turnover_stats(rebalances: list[Rebalance], commission: float) -> TurnoverStats:
    """Aggregate steady-state turnover. The initial entry (turnover ≡ 1.0) is a
    one-off and excluded from the means; cost-drag annualises the monthly mean."""
    steady = [r for r in rebalances if not r.is_entry]
    if not steady:
        return TurnoverStats(0.0, 0.0, 0.0, 0.0, 0)
    n = len(steady)
    mean_replaced = sum(r.names_replaced for r in steady) / n
    mean_pct = sum(r.names_replaced / r.size for r in steady) / n
    mean_to = sum(r.weight_turnover for r in steady) / n
    annual_cost = mean_to * commission * 12 * 100.0
    return TurnoverStats(mean_replaced, mean_pct, mean_to, annual_cost, n)


__all__ = [
    "FanCurve",
    "Panels",
    "Rebalance",
    "TurnoverStats",
    "monthly_rankings",
    "nav_from_selections",
    "score_ranking",
    "topk_fan",
    "turnover_stats",
]
