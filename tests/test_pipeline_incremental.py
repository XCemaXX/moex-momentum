"""Pre-tail hash safety gate for monthly recompute."""

from __future__ import annotations

import csv
import logging
from datetime import date, timedelta
from pathlib import Path

import pytest

from config import MASS_DRIFT_THRESHOLD
from momentum.pipeline import (
    IncrementalDriftError,
    _pre_tail_hash,
    _records_to_csv_bytes,
    compute_all,
    load_baseline_hashes,
    save_baseline_hashes,
)
from storage.records import write_records_atomic
from storage.schemas import MONTHLY_FIELDS, PRICE_FIELDS


def _daily_prices(start: str, n: int, base: float) -> list[dict[str, object]]:
    d0 = date.fromisoformat(start)
    out: list[dict[str, object]] = []
    for i in range(n):
        d = d0 + timedelta(days=i)
        out.append({"date": d.isoformat(), "close": base + i * 0.01, "value": 1_000_000_000.0})
    return out


def _write_prices(path: Path, rows: list[dict[str, object]]) -> None:
    write_records_atomic(path, rows, fieldnames=PRICE_FIELDS)


def _make_layout(
    tmp_path: Path, *, ticker: str, prices: list[dict[str, object]]
) -> dict[str, Path | None]:
    prices_dir = tmp_path / "p"
    dividends_dir = tmp_path / "d"
    splits_dir = tmp_path / "s"
    monthly_dir = tmp_path / "m"
    _write_prices(prices_dir / f"{ticker}.csv", prices)
    (dividends_dir).mkdir(exist_ok=True)
    (splits_dir).mkdir(exist_ok=True)
    return {
        "prices_iss_dir": prices_dir,
        "dividends_dir": dividends_dir,
        "splits_dir": splits_dir,
        "output_dir": monthly_dir,
    }


def _replace_jan_close(prices_path: Path, new_close: float) -> None:
    """Overwrite the 2023-01-31 row in a price CSV."""
    rows: list[dict[str, str]] = []
    with prices_path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r["date"] == "2023-01-31":
                r["close"] = str(new_close)
                r["value"] = "1000000000.0"
            rows.append(r)
    write_records_atomic(prices_path, rows, fieldnames=PRICE_FIELDS)


def test_pre_tail_hash_excludes_tail() -> None:
    recs = [
        {
            "month": f"2020-{m:02d}",
            "month_end_date": "2020-01-31",
            "close_adj": float(m),
            "monthly_value_rub": 0.0,
            "price_return": 0.0,
            "div_return": 0.0,
            "total_return": 0.0,
        }
        for m in range(1, 13)
    ] + [
        {
            "month": "2021-01",
            "month_end_date": "2021-01-31",
            "close_adj": 100.0,
            "monthly_value_rub": 0.0,
            "price_return": 0.0,
            "div_return": 0.0,
            "total_return": 0.0,
        },
        {
            "month": "2021-02",
            "month_end_date": "2021-02-28",
            "close_adj": 101.0,
            "monthly_value_rub": 0.0,
            "price_return": 0.0,
            "div_return": 0.0,
            "total_return": 0.0,
        },
    ]
    # tail_months=12 → pre-tail = 2 first rows.
    h_a = _pre_tail_hash(recs, tail_months=12)
    # Mutating tail rows should NOT change pre-tail hash.
    recs2 = list(recs)
    recs2[-1] = dict(recs2[-1], close_adj=999.0)
    h_b = _pre_tail_hash(recs2, tail_months=12)
    assert h_a == h_b
    # Mutating pre-tail row SHOULD change hash.
    recs3 = list(recs)
    recs3[0] = dict(recs3[0], close_adj=999.0)
    h_c = _pre_tail_hash(recs3, tail_months=12)
    assert h_a != h_c


def test_pre_tail_hash_short_history_returns_empty_hash() -> None:
    recs = [
        {
            "month": "2025-01",
            "month_end_date": "2025-01-31",
            "close_adj": 100.0,
            "monthly_value_rub": 0.0,
            "price_return": 0.0,
            "div_return": 0.0,
            "total_return": 0.0,
        }
    ]
    h = _pre_tail_hash(recs, tail_months=12)
    assert h == _pre_tail_hash([], tail_months=12)


def test_baseline_hashes_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "h.json"
    save_baseline_hashes(p, {"AAA": "deadbeef", "BBB": "cafebabe"})
    loaded = load_baseline_hashes(p)
    assert loaded == {"AAA": "deadbeef", "BBB": "cafebabe"}


def test_compute_all_first_run_seeds_baseline(tmp_path: Path) -> None:
    layout = _make_layout(
        tmp_path,
        ticker="AAA",
        prices=_daily_prices("2023-01-01", 400, 100.0),
    )
    compute_all(**layout, from_scratch=False)
    hashes = load_baseline_hashes(layout["output_dir"] / "_baseline_hashes.json")
    assert "AAA" in hashes


def test_compute_all_second_run_no_drift_passes(tmp_path: Path) -> None:
    layout = _make_layout(
        tmp_path,
        ticker="AAA",
        prices=_daily_prices("2023-01-01", 400, 100.0),
    )
    compute_all(**layout, from_scratch=False)
    # Append 10 more days — adds new tail month, pre-tail untouched.
    extra = _daily_prices("2024-02-05", 10, 200.0)
    rows = _daily_prices("2023-01-01", 400, 100.0) + extra
    _write_prices(layout["prices_iss_dir"] / "AAA.csv", rows)
    compute_all(**layout, from_scratch=False)  # must not raise


def test_compute_all_pre_tail_drift_raises(tmp_path: Path) -> None:
    layout = _make_layout(
        tmp_path,
        ticker="AAA",
        prices=_daily_prices("2023-01-01", 400, 100.0),
    )
    compute_all(**layout, from_scratch=False)
    _replace_jan_close(layout["prices_iss_dir"] / "AAA.csv", 9999.0)
    with pytest.raises(IncrementalDriftError):
        compute_all(**layout, from_scratch=False)


def test_compute_all_from_scratch_blesses_drift(tmp_path: Path) -> None:
    layout = _make_layout(
        tmp_path,
        ticker="AAA",
        prices=_daily_prices("2023-01-01", 400, 100.0),
    )
    compute_all(**layout, from_scratch=False)
    _replace_jan_close(layout["prices_iss_dir"] / "AAA.csv", 9999.0)
    compute_all(**layout, from_scratch=True)  # must not raise
    compute_all(**layout, from_scratch=False)  # baseline now updated


def test_compute_all_mass_drift_uses_softer_error(tmp_path: Path, caplog) -> None:
    n = MASS_DRIFT_THRESHOLD
    tickers = [f"T{i:03d}" for i in range(n)]
    prices_dir = tmp_path / "p"
    dividends_dir = tmp_path / "d"
    splits_dir = tmp_path / "s"
    monthly_dir = tmp_path / "m"
    dividends_dir.mkdir()
    splits_dir.mkdir()
    for t in tickers:
        _write_prices(prices_dir / f"{t}.csv", _daily_prices("2023-01-01", 400, 100.0))
    layout = {
        "prices_iss_dir": prices_dir,
        "dividends_dir": dividends_dir,
        "splits_dir": splits_dir,
        "output_dir": monthly_dir,
    }
    compute_all(**layout, from_scratch=False)  # seed baseline
    for t in tickers:
        _replace_jan_close(prices_dir / f"{t}.csv", 9999.0)

    caplog.set_level(logging.WARNING, logger="momentum.pipeline")
    with pytest.raises(IncrementalDriftError, match="mass-drift"):
        compute_all(**layout, from_scratch=False)
    assert any("mass-drift detected" in r.message for r in caplog.records)


def test_compute_all_single_drift_keeps_strict_error(tmp_path: Path) -> None:
    layout = _make_layout(
        tmp_path,
        ticker="AAA",
        prices=_daily_prices("2023-01-01", 400, 100.0),
    )
    compute_all(**layout, from_scratch=False)
    _replace_jan_close(layout["prices_iss_dir"] / "AAA.csv", 9999.0)
    with pytest.raises(IncrementalDriftError, match=r"drift in 1 ticker") as ei:
        compute_all(**layout, from_scratch=False)
    assert "mass-rebuild" not in str(ei.value)


def test_records_to_csv_bytes_matches_disk_write(tmp_path: Path) -> None:
    """Hash invariant: pre-tail hash equals sha256 of the corresponding
    on-disk bytes for the canonical MONTHLY_FIELDS schema.
    """
    recs: list[dict[str, object]] = [
        {
            "month": "2024-01",
            "month_end_date": "2024-01-31",
            "close_adj": 100.12345678,
            "monthly_value_rub": 0.0,
            "price_return": None,
            "div_return": 0.0,
            "total_return": None,
        },
        {
            "month": "2024-02",
            "month_end_date": "2024-02-29",
            "close_adj": 101.987654321,
            "monthly_value_rub": 0.0,
            "price_return": 0.0,
            "div_return": 0.0,
            "total_return": 0.0,
        },
    ]
    p = tmp_path / "out.csv"
    write_records_atomic(p, recs, fieldnames=MONTHLY_FIELDS)
    assert p.read_bytes() == _records_to_csv_bytes(recs)
