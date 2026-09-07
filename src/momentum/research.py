"""Precompute for the Experiments page: the a/b weight sweep and the top-K fan.

Both feed `compare.html`, which is skipped when their CSVs are absent, and both
are rebuilt on every push. That makes them part of the recurring pipeline, so
they live here behind `momentum compute sweep|fan` rather than in `scripts/`,
which is one-shot work run by hand.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from config import COMMISSION_PER_SIDE
from momentum.backtest import backtest
from momentum.signals import CurveFitSignal
from momentum.topn_fan import Panels, topk_fan
from storage.records import write_records_atomic
from tickers import TickersDict

LOG = logging.getLogger(__name__)

# a on r(12-1), b = 1 - a on r(6-1). a=1.0 ≡ `simple`, a=0.9 ≡ default `curve_fit`,
# so the fan subsumes both production signals.
A_WEIGHTS: tuple[float, ...] = tuple(round(1.0 - 0.1 * i, 1) for i in range(11))

K_GRID: tuple[int, ...] = (5, 8, 10, 13, 15, 18, 20, 23, 25, 28, 30)
# The fan varies concentration, not universe width, so the universe is pinned.
BASELINE_TOPN = 100

BASELINE_TOLERANCE = 1e-9


def _sweep_column(a: float) -> str:
    return f"a{a:.2f}"


def _nav_frame(navs: dict[str, pd.Series], mcftrr: pd.Series) -> pd.DataFrame:
    frame = pd.DataFrame(navs)
    frame["MCFTRR"] = mcftrr
    return frame


def write_nav_csv(path: Path, frame: pd.DataFrame) -> int:
    """Write a wide NAV frame as month + one column per curve. Returns row count."""
    rows = [
        {"month": str(m), **{str(c): float(v) for c, v in row.items()}}
        for m, row in frame.iterrows()
    ]
    write_records_atomic(path, rows, fieldnames=["month", *(str(c) for c in frame.columns)])
    return len(rows)


def weight_sweep(
    panels: Panels,
    tickers_dict: TickersDict,
    *,
    monthly_dir: Path,
    indices_dir: Path,
    start: pd.Period,
    a_weights: tuple[float, ...] = A_WEIGHTS,
) -> pd.DataFrame:
    """Q1 NAV per a/b weighting, plus MCFTRR. One panel load, one backtest per weight."""
    q1: dict[str, pd.Series] = {}
    mcftrr: pd.Series | None = None
    for a in a_weights:
        b = round(1.0 - a, 1)
        result = backtest(
            CurveFitSignal(a, b),
            monthly_dir=monthly_dir,
            indices_dir=indices_dir,
            tickers_dict=tickers_dict,
            start=start,
            panels=panels,
            with_pending=False,
        )
        q1[_sweep_column(a)] = result.q_values["Q1"]
        if mcftrr is None:
            mcftrr = result.q_values["MCFTRR"]
        LOG.info("a=%.1f b=%.1f: %d months", a, b, len(result.q_values))
    if mcftrr is None:
        raise ValueError("empty weight grid")
    return _nav_frame(q1, mcftrr)


def concentration_fan(
    panels: Panels,
    tickers_dict: TickersDict,
    *,
    monthly_dir: Path,
    indices_dir: Path,
    start: pd.Period,
    ks: tuple[int, ...] = K_GRID,
    top_n: int = BASELINE_TOPN,
    reference_q1: pd.Series | None = None,
) -> pd.DataFrame:
    """Top-K NAV per K, plus MCFTRR.

    `reference_q1` is the published curve_fit Q1 keyed by month string. When
    `top_n` matches the production universe the baseline run must reproduce it;
    a mismatch means the on-disk curve is stale and the fan would be built on a
    different universe than the page it shares an axis with.
    """
    # MCFTRR is topn-independent, so one baseline run supplies the benchmark
    # column and the reference check at once.
    res = backtest(
        CurveFitSignal(),
        monthly_dir=monthly_dir,
        indices_dir=indices_dir,
        tickers_dict=tickers_dict,
        start=start,
        universe_top_n=top_n,
        panels=panels,
        with_pending=False,
    )
    mcftrr = res.q_values["MCFTRR"].copy()
    mcftrr.index = pd.PeriodIndex(mcftrr.index, freq="M")

    if reference_q1 is not None:
        got = res.q_values["Q1"].copy()
        got.index = pd.PeriodIndex(got.index, freq="M").astype(str)
        merged = pd.concat([reference_q1, got], axis=1, join="inner")
        max_diff = float((merged.iloc[:, 0] - merged.iloc[:, 1]).abs().max())
        LOG.info("baseline check: max|Q1@%d − curve_fit Q1| = %.2e", top_n, max_diff)
        if max_diff >= BASELINE_TOLERANCE:
            raise ValueError(
                f"Q1@{top_n} diverges from the stored curve_fit Q1 by {max_diff:.2e} — "
                "recompute the backtest first"
            )

    fan = topk_fan(
        panels,
        CurveFitSignal(),
        tickers_dict,
        start=start,
        top_n=top_n,
        ks=list(ks),
        commission=COMMISSION_PER_SIDE,
    )
    for k, curve in fan.items():
        LOG.info("K=%d: %d months, %d rebalances", k, len(curve.nav), len(curve.rebalances))
    return _nav_frame({f"k{k}": c.nav for k, c in fan.items()}, mcftrr)
