"""Experiments-page precompute — the a/b weight sweep and the top-K fan."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from momentum.research import concentration_fan, weight_sweep, write_nav_csv
from storage.records import write_records_atomic
from storage.schemas import INDEX_FIELDS

_MONTHS = pd.period_range("2019-01", "2021-06", freq="M")


def _panels() -> tuple[tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame], dict[str, dict[str, str]]]:
    rng = np.random.default_rng(11)
    names = [f"T{i}" for i in range(8)]
    returns = pd.DataFrame({t: rng.normal(0.01, 0.05, len(_MONTHS)) for t in names}, index=_MONTHS)
    value = pd.DataFrame(
        {t: np.full(len(_MONTHS), 1e9 - i * 1e7) for i, t in enumerate(names)}, index=_MONTHS
    )
    return (returns, returns.copy(), value), {t: {"type": "share"} for t in names}


def _indices_dir(tmp_path: Path) -> Path:
    d = tmp_path / "indices"
    px = 1000.0
    rows = []
    for m in _MONTHS:
        rows.append({"date": m.to_timestamp(how="end").date().isoformat(), "close": px})
        px *= 1.01
    write_records_atomic(d / "MCFTRR.csv", rows, fieldnames=INDEX_FIELDS)
    return d


def test_sweep_has_one_column_per_weight_plus_benchmark(tmp_path: Path) -> None:
    panels, td = _panels()
    frame = weight_sweep(
        panels,
        td,  # type: ignore[arg-type]
        monthly_dir=tmp_path / "monthly",
        indices_dir=_indices_dir(tmp_path),
        start=_MONTHS[0],
        a_weights=(1.0, 0.5, 0.0),
    )
    assert list(frame.columns) == ["a1.00", "a0.50", "a0.00", "MCFTRR"]


def test_fan_rejects_a_stale_reference_curve(tmp_path: Path) -> None:
    """A reference Q1 the baseline run cannot reproduce means the on-disk
    backtest is stale — the fan must refuse rather than publish a mixed axis."""
    panels, td = _panels()
    args = {
        "monthly_dir": tmp_path / "monthly",
        "indices_dir": _indices_dir(tmp_path),
        "start": _MONTHS[0],
        "ks": (2, 4),
    }
    good = concentration_fan(panels, td, **args)  # type: ignore[arg-type]
    assert list(good.columns) == ["k2", "k4", "MCFTRR"]

    bogus = pd.Series(2.0, index=[str(m) for m in _MONTHS], name="Q1")
    bogus.index.name = "month"
    with pytest.raises(ValueError, match="diverges"):
        concentration_fan(panels, td, reference_q1=bogus, **args)  # type: ignore[arg-type]


def test_write_nav_csv_month_first(tmp_path: Path) -> None:
    frame = pd.DataFrame({"k2": [1.0, 1.1], "MCFTRR": [1.0, 1.02]}, index=_MONTHS[:2])
    out = tmp_path / "nested" / "fan.csv"
    assert write_nav_csv(out, frame) == 2
    with out.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert list(rows[0]) == ["month", "k2", "MCFTRR"]
    assert rows[1] == {"month": "2019-02", "k2": "1.1", "MCFTRR": "1.02"}
