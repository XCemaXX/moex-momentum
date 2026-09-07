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
its position contributes 0% — WARN-logged as one aggregate per run.

Output: q_values.csv (one row per month) + holdings/{YYYY-MM}.json.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from config import COMMISSION_PER_SIDE, UNIVERSE_TOP_N_LIQUID
from momentum.benchmark import mcftrr_monthly_returns
from momentum.nav import gross_return, turnover, warn_missing_returns
from momentum.pending import PendingEntry, compute_month_pending
from momentum.signals import Signal
from momentum.universe import liquidity_cut, load_panel, universe_at
from storage.records import write_json_atomic, write_records_atomic
from storage.schemas import Q_VALUES_FIELDS, SCORES_FIELDS, UNIVERSE_META_FIELDS
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


@dataclass(frozen=True)
class _Formation:
    """What forming the portfolio at one close produces, before any NAV update."""

    quartiles: dict[str, list[str]]
    scores: dict[str, float]
    meta: dict[str, object]
    pending: list[PendingEntry]


def _form_portfolio(
    t: pd.Period,
    *,
    signal: Signal,
    panels: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame],
    tickers_dict: TickersDict,
    universe_top_n: int | None,
    with_pending: bool,
) -> _Formation | None:
    """Rank the month's universe and cut it into quartiles. None if nothing is eligible."""
    returns_panel, close_panel, value_panel = panels
    universe = universe_at(
        t, returns_panel, tickers_dict, value_panel=value_panel, top_n=universe_top_n
    )
    if not universe:
        return None
    scores = signal.compute(returns_panel.loc[:, universe], t)
    quartiles = quartile_split(scores)
    cut = liquidity_cut(value_panel, t, universe) if not value_panel.empty else None
    # compute_month_pending returns [] when there is no liquidity floor
    # (incl. empty value_panel), so no extra guard is needed here.
    pending = (
        compute_month_pending(
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
        if with_pending
        else []
    )
    return _Formation(
        quartiles=quartiles,
        scores={str(tk): float(v) for tk, v in scores.dropna().items()},
        meta={
            "n": len(universe),
            "cut_rub": round(cut[1]) if cut else "",
            "marginal": cut[0] if cut else "",
        },
        pending=pending,
    )


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
    with_pending: bool = True,
) -> BacktestResult:
    """Run the quartile backtest. `start`/`end` are inclusive Period[M] bounds.

    `universe_top_n` keeps the N most liquid names each month (a relative cut by
    median monthly trading value, stable across years). None disables it.

    `panels` injects a pre-loaded (returns, close, value) tuple from `load_panel`
    so callers sweeping many signals over one panel pay the load once.

    `with_pending=False` skips the display-only pending block — it is ~60% of the
    run and only the curve_fit result is ever written.
    """
    returns_panel, close_panel, value_panel = (
        panels if panels is not None else load_panel(monthly_dir)
    )
    if returns_panel.empty:
        return BacktestResult(q_values=pd.DataFrame())

    misses: list[tuple[str, str, str]] = []
    months = returns_panel.index
    if start is not None:
        months = months[months >= start]
    if end is not None:
        months = months[months <= end]
    if len(months) == 0:
        return BacktestResult(q_values=pd.DataFrame())

    mcftrr_ret = mcftrr_monthly_returns(indices_dir)

    nav: dict[str, float] = {q: 1.0 for q in Q_LABELS}
    prev_w: dict[str, dict[str, float]] = {q: {} for q in Q_LABELS}
    holdings: dict[pd.Period, dict[str, list[str]]] = {}
    universe_meta: dict[pd.Period, dict[str, object]] = {}
    pending: dict[pd.Period, list[PendingEntry]] = {}
    scores_by_month: dict[pd.Period, dict[str, float]] = {}
    rows: list[dict[str, object]] = []
    mcftrr_nav = 1.0

    def rebalance_at(t: pd.Period) -> None:
        """Form the portfolio at close of t; it earns month t+1. No-op on an
        empty universe, which is what makes the cold start below degrade safely."""
        nonlocal prev_w
        formed = _form_portfolio(
            t,
            signal=signal,
            panels=(returns_panel, close_panel, value_panel),
            tickers_dict=tickers_dict,
            universe_top_n=universe_top_n,
            with_pending=with_pending,
        )
        if formed is None:
            return
        holdings[t] = formed.quartiles
        scores_by_month[t] = formed.scores
        universe_meta[t] = formed.meta
        if formed.pending:
            pending[t] = formed.pending
        LOG.debug("rebalance month=%s universe=%s", t, formed.meta["n"])
        new_w = {q: _weights(formed.quartiles[q]) for q in Q_LABELS}
        for q in Q_LABELS:
            nav[q] *= 1.0 - commission_per_side * turnover(prev_w[q], new_w[q])
        prev_w = new_w

    # Capital = 1.0 at the close before the first month in range.
    init_month = months[0] - 1
    rows.append({"month": str(init_month), **{q: 1.0 for q in Q_LABELS}, "MCFTRR": 1.0})

    # Form the portfolio at that close, so months[0] is earned by every series.
    # The benchmark earns it either way; a one-month offset between the two is
    # not a comparison. An empty universe here falls back to a cold start.
    rebalance_at(init_month)

    for t in months:
        # A month counts for both series or for neither: the benchmark stands in
        # for capital the strategy could have deployed, and it could not deploy
        # any before its first holdings exist.
        positioned = any(prev_w[q] for q in Q_LABELS)
        if positioned:
            month_returns = returns_panel.loc[t]
            for q in Q_LABELS:
                gr = gross_return(prev_w[q], month_returns, period=t, label=q, misses=misses)
                nav[q] *= 1.0 + gr
            if t in mcftrr_ret.index:
                r = mcftrr_ret.loc[t]
                if not math.isnan(r):
                    mcftrr_nav *= 1.0 + float(r)

        rebalance_at(t)
        rows.append({"month": str(t), **{q: nav[q] for q in Q_LABELS}, "MCFTRR": mcftrr_nav})

    warn_missing_returns(misses, label=type(signal).__name__)
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
            fieldnames=UNIVERSE_META_FIELDS,
        )

    if result.scores:
        # Full-precision scores (task 025): the site re-orders Q1-Q4 by this and
        # rounds for display only. Long-form month,ticker,score.
        score_rows: list[dict[str, object]] = [
            {"month": str(p), "ticker": tk, "score": s}
            for p, per_month in sorted(result.scores.items())
            for tk, s in per_month.items()
        ]
        write_records_atomic(output_dir / "scores.csv", score_rows, fieldnames=SCORES_FIELDS)

    if write_pending:
        pending_obj = {
            str(p): [e.to_dict() for e in entries] for p, entries in sorted(result.pending.items())
        }
        write_json_atomic(output_dir / "pending.json", pending_obj)

    for period, quartiles in result.holdings.items():
        write_json_atomic(holdings_dir / f"{period}.json", quartiles)
