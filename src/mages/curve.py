"""Mages index equity curve on the monthly grid (task 002, phase 1).

C1 rotation: the quarter published in Jan/Apr/Jul/Oct takes effect from that
same calendar month. Weights are held with intra-quarter drift and reset to the
new target at each quarter start; a commission is charged on the rebalance
turnover, mirroring the quartile backtest so the two are comparable. Returns are
total-return, equity sleeve only — non-investable instruments are already out of
`shares` in data/mages.

A held ticker with no return for a month contributes 0% (flat), same as the
backtest engine. A share with no price panel at all is dropped and the quarter's
weights re-normalized, with a WARN.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from config import COMMISSION_PER_SIDE
from mages.loader import MagesQuarter
from momentum.benchmark import mcftrr_monthly_returns
from momentum.universe import load_panel

LOG = logging.getLogger(__name__)


def _turnover(old: dict[str, float], new: dict[str, float]) -> float:
    keys = set(old) | set(new)
    return sum(abs(new.get(k, 0.0) - old.get(k, 0.0)) for k in keys)


def _panel_weights(weights: dict[str, float], columns: set[str]) -> dict[str, float]:
    """Keep only tickers with a price panel, re-normalize to sum 1."""
    avail = {tk: w for tk, w in weights.items() if tk in columns}
    dropped = set(weights) - set(avail)
    if dropped:
        LOG.warning("mages: no price panel for %s — dropped, re-normalized", sorted(dropped))
    s = sum(avail.values())
    return {tk: w / s for tk, w in avail.items()} if s > 0 else {}


def mages_nav(
    quarters: list[MagesQuarter],
    returns_panel: pd.DataFrame,
    *,
    commission_per_side: float = COMMISSION_PER_SIDE,
) -> pd.Series:
    """NAV series (start = 1.0 the month before the first quarter), Period[M]."""
    if returns_panel.empty or not quarters:
        return pd.Series(dtype=float)
    cols = set(returns_panel.columns)
    targets = {q.period: _panel_weights(q.weights, cols) for q in quarters}
    first = min(targets)
    if first not in returns_panel.index:  # else the first quarter never rebalances
        LOG.warning("mages: first quarter month %s absent from price panel", first)
    months = returns_panel.index[returns_panel.index >= first]
    if len(months) == 0:
        return pd.Series(dtype=float)

    nav = 1.0
    held: dict[str, float] = {}
    idx: list[pd.Period] = [first - 1]
    vals: list[float] = [1.0]
    for t in months:
        if t in targets:  # quarter start: rebalance at prior close, then earn month t
            tgt = targets[t]
            nav *= 1.0 - commission_per_side * _turnover(held, tgt)
            held = dict(tgt)
        if held:
            r = returns_panel.loc[t]
            grown: dict[str, float] = {}
            port_growth = 0.0
            for tk, w in held.items():
                ri = r.get(tk)
                rv = 0.0 if (ri is None or pd.isna(ri)) else float(ri)
                grown[tk] = w * (1.0 + rv)
                port_growth += grown[tk]
            if port_growth > 0:
                nav *= port_growth
                held = {tk: g / port_growth for tk, g in grown.items()}  # drift
        idx.append(t)
        vals.append(nav)
    return pd.Series(vals, index=pd.PeriodIndex(idx, freq="M"), dtype=float)


def _mcftrr_nav(indices_dir: Path, index: pd.PeriodIndex) -> pd.Series:
    """MCFTRR NAV aligned to `index`, rebased to 1.0 at index[0]."""
    ret = mcftrr_monthly_returns(indices_dir)
    nav = 1.0
    vals: list[float] = []
    for i, p in enumerate(index):
        rr = ret.get(p)
        if i > 0 and rr is not None and not pd.isna(rr):
            nav *= 1.0 + float(rr)
        vals.append(nav)
    return pd.Series(vals, index=index, dtype=float)


def build_mages_frame(
    quarters: list[MagesQuarter],
    *,
    monthly_dir: Path,
    indices_dir: Path,
    commission_per_side: float = COMMISSION_PER_SIDE,
) -> pd.DataFrame:
    """DataFrame indexed Period[M] with columns Mages, MCFTRR — both NAV start 1."""
    tickers = sorted({tk for q in quarters for tk in q.weights})
    returns_panel = load_panel(monthly_dir, ticker_filter=tickers)[0]
    mages = mages_nav(quarters, returns_panel, commission_per_side=commission_per_side)
    if mages.empty:
        return pd.DataFrame()
    mcftrr = _mcftrr_nav(indices_dir, pd.PeriodIndex(mages.index, freq="M"))
    return pd.DataFrame({"Mages": mages, "MCFTRR": mcftrr})
