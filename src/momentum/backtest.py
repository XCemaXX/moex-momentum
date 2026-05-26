"""Quartile backtest engine.

Mechanics (plan §9, locked decision #10 — signal-and-execute on one close):
    1. At close of month t, holdings chosen at close of (t-1) earn the month's
       total_return → gross_return_t applied to NAV.
    2. Then at the same close, signal(t) is computed, holdings rebalanced for
       month t+1, and the rebalance cost is applied to NAV.
    3. Cost = COMMISSION_PER_SIDE × Σ |Δw_i| across the union of old/new
       holdings; entering from empty holdings yields turnover = 1.0.

NAV[t] = NAV[t-1] × (1 + gross_return_t) × (1 - cost_at_t).

If a held ticker has no total_return for the following month (delisting, gap),
its position contributes 0% — WARN-logged once per occurrence.

Output: q_values.csv (one row per month) + holdings/{YYYY-MM}.json.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pandas as pd

from config import COMMISSION_PER_SIDE, UNIVERSE_TOP_N_LIQUID
from momentum.pending import PendingEntry, compute_month_pending
from momentum.signals import Signal
from momentum.universe import liquidity_cut, load_panel, universe_at
from storage.records import read_records, write_records_atomic
from storage.schemas import INDEX_CASTS, Q_VALUES_FIELDS
from tickers import TickersDict

LOG = logging.getLogger(__name__)

NUM_QUANTILES = 4
Q_LABELS = [f"Q{i}" for i in range(1, NUM_QUANTILES + 1)]


@dataclass
class BacktestResult:
    q_values: pd.DataFrame  # index Period[M], cols Q1..Q4 + MCFTRR
    holdings: dict[pd.Period, dict[str, list[str]]] = field(default_factory=dict)
    # Per-rebalance universe diagnostics: month -> {n, cut_rub, marginal}.
    universe_meta: dict[pd.Period, dict[str, object]] = field(default_factory=dict)
    # Display-only (task 008): young liquid tickers with no q yet, per month.
    pending: dict[pd.Period, list[PendingEntry]] = field(default_factory=dict)
    # Per-month momentum score by ticker (task 025): the rank quartile_split used,
    # kept full-precision so the site can re-order Q1-Q4 and slice top-K.
    scores: dict[pd.Period, dict[str, float]] = field(default_factory=dict)


def quartile_split(scores: pd.Series) -> dict[str, list[str]]:
    """Rank scores DESC (tie-break ticker ASC) and split into 4 buckets.

    Buckets sized as evenly as possible; the remainder goes to top quartiles
    (Q1, Q2, ...) — so |Q1| ≥ |Q4| with at most a one-element difference.
    """
    scores = scores.dropna()
    if scores.empty:
        return {q: [] for q in Q_LABELS}
    pairs = sorted(scores.items(), key=lambda kv: (-float(kv[1]), str(kv[0])))
    n = len(pairs)
    base, rem = divmod(n, NUM_QUANTILES)
    sizes = [base + (1 if i < rem else 0) for i in range(NUM_QUANTILES)]
    out: dict[str, list[str]] = {}
    cursor = 0
    for label, size in zip(Q_LABELS, sizes, strict=True):
        out[label] = sorted(str(tk) for tk, _ in pairs[cursor : cursor + size])
        cursor += size
    return out


def _weights(tickers: list[str]) -> dict[str, float]:
    if not tickers:
        return {}
    w = 1.0 / len(tickers)
    return {tk: w for tk in tickers}


def turnover(old_w: dict[str, float], new_w: dict[str, float]) -> float:
    keys = set(old_w) | set(new_w)
    return sum(abs(new_w.get(k, 0.0) - old_w.get(k, 0.0)) for k in keys)


def gross_return(
    weights: dict[str, float],
    monthly_returns: pd.Series,
    *,
    period: pd.Period,
    quartile: str,
) -> float:
    """Equal-weight portfolio gross return. Missing per-ticker return → 0% with WARN."""
    if not weights:
        return 0.0
    total = 0.0
    for tk, w in weights.items():
        r = monthly_returns.get(tk)
        if r is None or (isinstance(r, float) and math.isnan(r)):
            LOG.warning(
                "missing total_return month=%s ticker=%s quartile=%s — treated as 0",
                period,
                tk,
                quartile,
            )
            continue
        total += w * float(r)
    return total


def _mcftrr_monthly(indices_dir: Path) -> pd.Series:
    """Last close of each month → monthly pct_change for MCFTRR benchmark."""
    rows = read_records(indices_dir / "MCFTRR.csv", casts=INDEX_CASTS)
    if not rows:
        return pd.Series(dtype=float)
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    period_idx = cast(pd.DatetimeIndex, df.index).to_period("M")
    last_per_month = df["close"].astype(float).groupby(period_idx).tail(1)
    s = pd.Series(
        last_per_month.values,
        index=cast(pd.DatetimeIndex, last_per_month.index).to_period("M"),
        dtype=float,
    )
    s.index.name = "month"
    return s.pct_change()


def backtest(
    signal: Signal,
    *,
    monthly_dir: Path,
    indices_dir: Path,
    tickers_dict: TickersDict,
    start: pd.Period | None = None,
    end: pd.Period | None = None,
    commission_per_side: float = COMMISSION_PER_SIDE,
    universe_top_n: int | None = UNIVERSE_TOP_N_LIQUID,
    panels: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame] | None = None,
) -> BacktestResult:
    """Run the quartile backtest. `start`/`end` are inclusive Period[M] bounds.

    `universe_top_n` keeps the N most liquid names each month (a relative cut by
    median monthly trading value, stable across years). None disables it.

    `panels` injects a pre-loaded (returns, close, value) tuple from `load_panel`
    so callers sweeping many signals over one panel pay the load once.
    """
    returns_panel, close_panel, value_panel = (
        panels if panels is not None else load_panel(monthly_dir)
    )
    if returns_panel.empty:
        return BacktestResult(q_values=pd.DataFrame())

    months = returns_panel.index
    if start is not None:
        months = months[months >= start]
    if end is not None:
        months = months[months <= end]
    if len(months) == 0:
        return BacktestResult(q_values=pd.DataFrame())

    mcftrr_ret = _mcftrr_monthly(indices_dir)

    nav: dict[str, float] = {q: 1.0 for q in Q_LABELS}
    prev_w: dict[str, dict[str, float]] = {q: {} for q in Q_LABELS}
    holdings: dict[pd.Period, dict[str, list[str]]] = {}
    universe_meta: dict[pd.Period, dict[str, object]] = {}
    pending: dict[pd.Period, list[PendingEntry]] = {}
    scores_by_month: dict[pd.Period, dict[str, float]] = {}
    rows: list[dict[str, object]] = []
    mcftrr_nav = 1.0

    # Initial row: one month before the first month in range, NAV=1.0.
    init_month = months[0] - 1
    rows.append({"month": str(init_month), **{q: 1.0 for q in Q_LABELS}, "MCFTRR": 1.0})

    for t in months:
        # 1. Apply previously-set holdings' return over month t.
        if any(prev_w[q] for q in Q_LABELS):
            month_returns = returns_panel.loc[t]
            for q in Q_LABELS:
                gr = gross_return(prev_w[q], month_returns, period=t, quartile=q)
                nav[q] *= 1.0 + gr
        # MCFTRR benchmark mirrors the same timing.
        if t in mcftrr_ret.index:
            r = mcftrr_ret.loc[t]
            if not math.isnan(r):
                mcftrr_nav *= 1.0 + float(r)

        # 2. Rebalance at close of t (if universe non-empty).
        universe = universe_at(
            t,
            returns_panel,
            tickers_dict,
            value_panel=value_panel,
            top_n=universe_top_n,
        )
        if universe:
            scores = signal.compute(returns_panel.loc[:, universe], t)
            quartiles = quartile_split(scores)
            holdings[t] = quartiles
            scores_by_month[t] = {str(tk): float(v) for tk, v in scores.dropna().items()}
            cut = liquidity_cut(value_panel, t, universe) if not value_panel.empty else None
            universe_meta[t] = {
                "n": len(universe),
                "cut_rub": round(cut[1]) if cut else "",
                "marginal": cut[0] if cut else "",
            }
            # compute_month_pending returns [] when there is no liquidity floor
            # (incl. empty value_panel), so no extra guard is needed here.
            month_pending = compute_month_pending(
                t,
                returns_panel=returns_panel,
                close_panel=close_panel,
                value_panel=value_panel,
                tickers_dict=tickers_dict,
                universe=universe,
                scores=scores,
                quartiles=quartiles,
                liquidity_floor=cut[1] if cut else None,
            )
            if month_pending:
                pending[t] = month_pending
            LOG.info(
                "rebalance month=%s universe=%d Q1=%d Q4=%d",
                t,
                len(universe),
                len(quartiles["Q1"]),
                len(quartiles["Q4"]),
            )
            new_w = {q: _weights(quartiles[q]) for q in Q_LABELS}
            for q in Q_LABELS:
                cost = commission_per_side * turnover(prev_w[q], new_w[q])
                nav[q] *= 1.0 - cost
            prev_w = new_w

        rows.append({"month": str(t), **{q: nav[q] for q in Q_LABELS}, "MCFTRR": mcftrr_nav})

    df = pd.DataFrame(rows).drop_duplicates(subset=["month"], keep="last")
    df = df.set_index("month").sort_index()
    return BacktestResult(
        q_values=df,
        holdings=holdings,
        universe_meta=universe_meta,
        pending=pending,
        scores=scores_by_month,
    )


def write_backtest(
    result: BacktestResult, *, output_dir: Path, write_pending: bool = False
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    holdings_dir = output_dir / "holdings"
    holdings_dir.mkdir(parents=True, exist_ok=True)

    q_rows: list[dict[str, object]] = [
        {"month": str(idx), **{str(c): float(v) for c, v in row.items()}}
        for idx, row in result.q_values.iterrows()
    ]
    write_records_atomic(output_dir / "q_values.csv", q_rows, fieldnames=Q_VALUES_FIELDS)

    if result.universe_meta:
        meta_rows: list[dict[str, object]] = [
            {"month": str(p), "n": m["n"], "cut_rub": m["cut_rub"], "marginal": m["marginal"]}
            for p, m in sorted(result.universe_meta.items())
        ]
        write_records_atomic(
            output_dir / "universe_meta.csv",
            meta_rows,
            fieldnames=("month", "n", "cut_rub", "marginal"),
        )

    if result.scores:
        # Full-precision scores (task 025): the site re-orders Q1-Q4 by this and
        # rounds for display only. Long-form month,ticker,score.
        score_rows: list[dict[str, object]] = [
            {"month": str(p), "ticker": tk, "score": s}
            for p, per_month in sorted(result.scores.items())
            for tk, s in per_month.items()
        ]
        write_records_atomic(
            output_dir / "scores.csv", score_rows, fieldnames=("month", "ticker", "score")
        )

    if write_pending:
        pending_obj = {
            str(p): [e.to_dict() for e in entries] for p, entries in sorted(result.pending.items())
        }
        path = output_dir / "pending.json"
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(pending_obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)

    for period, quartiles in result.holdings.items():
        path = holdings_dir / f"{period}.json"
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(quartiles, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
