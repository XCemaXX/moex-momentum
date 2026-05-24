"""Weight-sweep of the curve_fit momentum signal — research precompute.

score = (a·r(12-1) + b·r(6-1)) / σ(12),  b = 1 - a,  a ∈ {1.0, 0.9, ..., 0.0}.

Endpoints coincide with the production signals: a=1.0 ≡ `simple` (r12/σ),
a=0.9 ≡ default `curve_fit`. So the 11-line fan subsumes both reference lines.

One panel load, 11 backtests, one wide CSV of Q1 NAV curves (+ MCFTRR) for the
site explorer (compare.html). Output is gitignored (data/momentum/ per task 014);
CI runs this before `momentum site build`. Same mechanics as the on-disk signals,
so the a=0.9 column matches data/momentum/curve_fit q_values Q1 exactly.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

import tickers as t_mod
from config import ANALYSIS_START_DATE
from momentum.backtest import backtest
from momentum.signals import CurveFitSignal
from momentum.universe import load_panel
from storage.records import write_records_atomic

ROOT = Path(__file__).resolve().parents[1]
MONTHLY_DIR = ROOT / "data" / "momentum" / "monthly"
INDICES_DIR = ROOT / "data" / "indices"
TICKERS_FILE = ROOT / "data" / "tickers.json"
OUT_FILE = ROOT / "data" / "momentum" / "sweep" / "q1_nav.csv"

# a-weights on r(12-1); b = 1 - a on r(6-1). Step 0.1, high → low.
A_WEIGHTS: tuple[float, ...] = tuple(round(1.0 - 0.1 * i, 1) for i in range(11))


def _col(a: float) -> str:
    return f"a{a:.2f}"


def main() -> None:
    tickers_dict = t_mod.load(TICKERS_FILE)
    if not tickers_dict:
        raise SystemExit(f"{TICKERS_FILE} is empty — run `momentum tickers refresh` first")

    panels = load_panel(MONTHLY_DIR)
    start = pd.Period(ANALYSIS_START_DATE, freq="M")

    q1: dict[str, pd.Series] = {}
    mcftrr: pd.Series | None = None
    for a in A_WEIGHTS:
        b = round(1.0 - a, 1)
        result = backtest(
            CurveFitSignal(a, b),
            monthly_dir=MONTHLY_DIR,
            indices_dir=INDICES_DIR,
            tickers_dict=tickers_dict,
            start=start,
            panels=panels,
        )
        q1[_col(a)] = result.q_values["Q1"]
        if mcftrr is None:
            mcftrr = result.q_values["MCFTRR"]
        print(f"a={a:.1f} b={b:.1f}: {len(result.q_values)} months")

    assert mcftrr is not None
    frame = pd.DataFrame({**q1, "MCFTRR": mcftrr})
    rows = [
        {"month": str(m), **{c: float(v) for c, v in row.items()}} for m, row in frame.iterrows()
    ]
    fieldnames = ["month", *(_col(a) for a in A_WEIGHTS), "MCFTRR"]
    write_records_atomic(OUT_FILE, rows, fieldnames=fieldnames)
    print(f"sweep: {len(rows)} months × {len(A_WEIGHTS)} weights → {OUT_FILE}")


if __name__ == "__main__":
    main()
