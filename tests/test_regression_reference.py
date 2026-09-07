"""Q-curves recomputed from committed raw must match the frozen reference.

This is the regression net for the whole compute chain: ingest → splits/dividend
adjust → monthly → signal → backtest. A refactor that moves any link shows up
here, on the published numbers rather than on a unit-level proxy.

Comparison is numeric, not byte-wise: NAV is a 165-step product, and a float ulp
shift on a numpy upgrade is not a regression. `1e-12` sits far below any
meaningful change in the strategy and far above that noise.

Re-blessing: a monthly data update adds one row per signal and turns this red on
purpose. Copy the new `q_values.csv` over the reference — the diff is then the
record of what the month contributed. More than one changed row means history
moved; say why in the commit.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import tickers as t_mod
from momentum.universe import rename_edges
from tests.conftest import DATA_DIR, REFERENCE_DIR, SIGNALS_UNDER_TEST, Computed

REL_TOL = 1e-12


def _load(path: Path) -> pd.DataFrame:
    return pd.read_csv(path).set_index("month").sort_index()


@pytest.mark.parametrize("signal", SIGNALS_UNDER_TEST)
def test_q_values_match_reference(signal: str, computed: Computed) -> None:
    ref_path = REFERENCE_DIR / f"q_values_{signal}.csv"
    got = _load(computed.signal_dir(signal) / "q_values.csv")
    want = _load(ref_path)

    assert list(got.columns) == list(want.columns), f"{signal}: column set changed"
    assert list(got.index) == list(want.index), (
        f"{signal}: month index differs. A new month is expected after a data "
        f"update — re-bless tests/reference/q_values_{signal}.csv, see README "
        f"§Monthly update."
    )

    diff = (got - want).abs() / want.abs()
    worst = float(diff.max().max())
    assert worst < REL_TOL, (
        f"{signal}: worst relative deviation {worst:.3e} exceeds {REL_TOL:.0e}. "
        f"A code change that moves published numbers is a real regression; if it "
        f"is intended, re-bless the reference and record the delta in the commit."
    )


def test_no_renamed_duplicates_in_holdings(computed: Computed) -> None:
    """One issuer, one slot: a rename must not put both SECIDs in the same month."""
    edges = rename_edges(t_mod.load(DATA_DIR / "tickers.json"))
    bad: list[str] = []
    for path in sorted((computed.signal_dir("curve_fit") / "holdings").glob("*.json")):
        with path.open(encoding="utf-8") as f:
            held = {tk for names in json.load(f).values() for tk in names}
        bad += [f"{path.stem}: {pred}+{succ}" for pred, succ, _ in edges if {pred, succ} <= held]
    assert not bad, f"both legs of a rename held at once: {bad[:5]}"
