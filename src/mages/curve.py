"""Mages index equity curve on the monthly grid (task 002, phase 1).

C1 rotation: the quarter published in Jan/Apr/Jul/Oct takes effect from that
same calendar month. Weights are held with intra-quarter drift and reset to the
new target at each quarter start; a commission is charged on the rebalance
turnover, mirroring the quartile backtest so the two are comparable. Returns are
total-return, equity sleeve only — non-investable instruments are already out of
`shares` in data/mages.

Snapshots name a redomiciled issuer by its new ticker before that ticker
trades; such months take the predecessor's return. A held ticker still without
a return contributes 0% (flat), same as the backtest engine, and is reported by
`flat_positions`. A share with no price panel at all is dropped and the
quarter's weights re-normalized, with a WARN.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from config import COMMISSION_PER_SIDE
from mages.loader import MagesQuarter
from momentum.benchmark import mcftrr_monthly_returns
from momentum.nav import turnover
from momentum.universe import load_panel
from tickers import ManualEntry

LOG = logging.getLogger(__name__)


Predecessors = Mapping[str, tuple[str, pd.Period]]


@dataclass(frozen=True)
class FlatPosition:
    quarter: str
    month: pd.Period
    ticker: str
    weight: float  # quarter target weight


def redomicile_predecessors(tickers_manual: list[ManualEntry]) -> dict[str, tuple[str, pd.Period]]:
    """successor -> (predecessor, month of the redomicile)."""
    out: dict[str, tuple[str, pd.Period]] = {}
    for rec in tickers_manual:
        old, new = rec.get("old_secid"), rec.get("new_secid")
        if rec.get("type") == "redomicile" and old and new and old != new:
            out[new] = (old, pd.Period(rec["renamed"], freq="M"))
    return out


def with_predecessors(returns_panel: pd.DataFrame, predecessors: Predecessors) -> pd.DataFrame:
    """Fill a successor's missing months up to its redomicile month from the predecessor.

    The redomicile month itself is included: the successor's first month has no
    return, while the predecessor usually traded part of it.
    """
    out = returns_panel.copy()
    for succ, (pred, renamed) in predecessors.items():
        if pred not in out.columns:
            continue
        donor = out[pred].where(out.index <= renamed)
        out[succ] = out[succ].fillna(donor) if succ in out.columns else donor
    return out


def flat_positions(quarters: list[MagesQuarter], returns_panel: pd.DataFrame) -> list[FlatPosition]:
    """Held positions with no return in a month inside the panel — booked as 0%."""
    if returns_panel.empty:
        return []
    cols = set(returns_panel.columns)
    ordered = sorted(quarters, key=lambda q: q.period)
    last = returns_panel.index.max()
    out: list[FlatPosition] = []
    for i, q in enumerate(ordered):
        end = ordered[i + 1].period - 1 if i + 1 < len(ordered) else last
        months = returns_panel.index[
            (returns_panel.index >= q.period) & (returns_panel.index <= end)
        ]
        for tk, w in _panel_weights(q.weights, cols).items():
            for t in months:
                if pd.isna(returns_panel.at[t, tk]):
                    out.append(FlatPosition(q.quarter, t, tk, w))
    return out


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
            nav *= 1.0 - commission_per_side * turnover(held, tgt)
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
    predecessors: Predecessors | None = None,
    commission_per_side: float = COMMISSION_PER_SIDE,
) -> pd.DataFrame:
    """DataFrame indexed Period[M] with columns Mages, MCFTRR — both NAV start 1."""
    predecessors = predecessors or {}
    held = {tk for q in quarters for tk in q.weights}
    tickers = sorted(held | {predecessors[tk][0] for tk in held if tk in predecessors})
    returns_panel = with_predecessors(
        load_panel(monthly_dir, ticker_filter=tickers)[0], predecessors
    )
    flat = flat_positions(quarters, returns_panel)
    if flat:
        LOG.warning(
            "mages: %d position-month(s) without a return booked as 0%%: %s",
            len(flat),
            ", ".join(f"{f.ticker} {f.month} ({f.weight:.1%})" for f in flat),
        )
    mages = mages_nav(quarters, returns_panel, commission_per_side=commission_per_side)
    if mages.empty:
        return pd.DataFrame()
    mcftrr = _mcftrr_nav(indices_dir, pd.PeriodIndex(mages.index, freq="M"))
    return pd.DataFrame({"Mages": mages, "MCFTRR": mcftrr})
