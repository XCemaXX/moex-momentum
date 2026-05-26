"""Top-N concentration fan — site precompute (task 024).

Fixes the top-100 liquid universe and holds the top-K names by score,
K ∈ {5,8,…,30}. Writes the wide NAV CSV to
data/momentum/topn_fan/fan_concentration.csv (gitignored, task 014) — the only
artefact the Experiments page reads. K=25 ≈ full Q1; K=30 dips into Q2.

Run: `python scripts/compute_topn_fan.py`.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

import tickers as t_mod
from config import ANALYSIS_START_DATE, COMMISSION_PER_SIDE
from momentum.backtest import backtest
from momentum.signals import CurveFitSignal
from momentum.topn_fan import topk_fan
from momentum.universe import load_panel
from storage.records import write_records_atomic

ROOT = Path(__file__).resolve().parents[1]
MONTHLY_DIR = ROOT / "data" / "momentum" / "monthly"
INDICES_DIR = ROOT / "data" / "indices"
TICKERS_FILE = ROOT / "data" / "tickers.json"
CURVE_FIT_Q = ROOT / "data" / "momentum" / "curve_fit" / "q_values.csv"
OUT_DIR = ROOT / "data" / "momentum" / "topn_fan"

K_GRID: tuple[int, ...] = (5, 8, 10, 13, 15, 18, 20, 23, 25, 28, 30)
BASELINE_TOPN = 100


def _write_fan_csv(path: Path, navs: dict[int, pd.Series], mcftrr: pd.Series, prefix: str) -> None:
    frame = pd.DataFrame({f"{prefix}{n}": s for n, s in navs.items()})
    frame["MCFTRR"] = mcftrr
    rows = [
        {"month": str(m), **{c: float(v) for c, v in row.items()}} for m, row in frame.iterrows()
    ]
    fieldnames = ["month", *(f"{prefix}{n}" for n in navs), "MCFTRR"]
    write_records_atomic(path, rows, fieldnames=fieldnames)


def main() -> None:
    tickers_dict = t_mod.load(TICKERS_FILE)
    if not tickers_dict:
        raise SystemExit(f"{TICKERS_FILE} is empty — run `momentum tickers refresh` first")

    panels = load_panel(MONTHLY_DIR)
    if panels[0].empty:
        raise SystemExit(f"no monthly panel at {MONTHLY_DIR} — run `momentum compute monthly`")
    start = pd.Period(ANALYSIS_START_DATE, freq="M")

    # One baseline backtest: MCFTRR is topn-independent (read straight from the
    # index file), so a single top-100 run supplies the benchmark column and the
    # Q1 sanity check below.
    res = backtest(
        CurveFitSignal(),
        monthly_dir=MONTHLY_DIR,
        indices_dir=INDICES_DIR,
        tickers_dict=tickers_dict,  # type: ignore[arg-type]
        start=start,
        universe_top_n=BASELINE_TOPN,
        panels=panels,
    )
    mcftrr = res.q_values["MCFTRR"].copy()
    mcftrr.index = pd.PeriodIndex(mcftrr.index, freq="M")

    # Sanity: top-100 Q1 must equal the on-disk production curve_fit Q1.
    if CURVE_FIT_Q.exists():
        ref = pd.read_csv(CURVE_FIT_Q).set_index("month")["Q1"]
        got = res.q_values["Q1"].copy()
        got.index = pd.PeriodIndex(got.index, freq="M").astype(str)
        merged = pd.concat([ref, got], axis=1, join="inner")
        max_diff = float((merged.iloc[:, 0] - merged.iloc[:, 1]).abs().max())
        print(f"baseline check: max|Q1@100 − curve_fit Q1| = {max_diff:.2e}")
        assert max_diff < 1e-9, "Q1@100 diverges from production curve_fit Q1"

    # Concentration fan: top-K by score from the fixed top-100 universe.
    fan = topk_fan(
        panels,
        CurveFitSignal(),
        tickers_dict,  # type: ignore[arg-type]
        start=start,
        top_n=BASELINE_TOPN,
        ks=list(K_GRID),
        commission=COMMISSION_PER_SIDE,
    )
    for k, curve in fan.items():
        print(f"K={k}: {len(curve.nav)} months, {len(curve.rebalances)} rebalances")
    fan_navs = {k: c.nav for k, c in fan.items()}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_fan_csv(OUT_DIR / "fan_concentration.csv", fan_navs, mcftrr, "k")
    print(f"fan → {OUT_DIR / 'fan_concentration.csv'}")


if __name__ == "__main__":
    main()
