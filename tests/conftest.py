"""Shared fixtures.

`computed` reruns the production chain over committed raw data. It costs ~30 s
once per session. Paying it is deliberate: the alternative is reading
`data/momentum/`, which is gitignored — and guarding on its absence is exactly
how two regression tests stayed dead in CI for months.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pytest

import tickers as t_mod
from config import ANALYSIS_START_DATE
from momentum.backtest import backtest, write_backtest
from momentum.pipeline import compute_all
from momentum.signals import SIGNALS
from momentum.universe import load_panel

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
REFERENCE_DIR = Path(__file__).resolve().parent / "reference"

SIGNALS_UNDER_TEST: tuple[str, ...] = ("curve_fit", "simple")


@dataclass(frozen=True)
class Computed:
    """Monthly panel plus both signals, written the way the CLI writes them."""

    monthly_dir: Path
    out_root: Path
    panels: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]

    def signal_dir(self, signal: str) -> Path:
        return self.out_root / signal


@pytest.fixture(scope="session")
def computed(tmp_path_factory: pytest.TempPathFactory) -> Computed:
    root = tmp_path_factory.mktemp("computed")
    monthly_dir = root / "monthly"
    compute_all(
        prices_iss_dir=DATA_DIR / "prices_iss",
        dividends_dir=DATA_DIR / "dividends",
        splits_dir=DATA_DIR / "splits",
        output_dir=monthly_dir,
        from_scratch=True,
    )
    panels = load_panel(monthly_dir)
    tickers_dict = t_mod.load(DATA_DIR / "tickers.json")
    start = pd.Period(ANALYSIS_START_DATE, freq="M")
    for name in SIGNALS_UNDER_TEST:
        result = backtest(
            SIGNALS[name],
            monthly_dir=monthly_dir,
            indices_dir=DATA_DIR / "indices",
            tickers_dict=tickers_dict,
            start=start,
            panels=panels,
            # pending is display-only and does not enter q_values.
            with_pending=False,
        )
        write_backtest(result, output_dir=root / name)
    return Computed(monthly_dir=monthly_dir, out_root=root, panels=panels)
