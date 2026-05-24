"""Tests for dividend-gap detector (corporate/dividend_gaps.py)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from adjustments.dividend_gaps import compute_gaps, load_acked, save_gaps
from storage.records import write_records_atomic
from storage.schemas import DIV_FIELDS, PRICE_FIELDS


def _write_prices(path: Path, records: list[dict[str, Any]]) -> None:
    write_records_atomic(path, records, fieldnames=PRICE_FIELDS)


def _write_divs(path: Path, records: list[dict[str, Any]]) -> None:
    write_records_atomic(path, records, fieldnames=DIV_FIELDS)


def test_compute_gaps_flags_year_without_div(tmp_path: Path) -> None:
    prices = tmp_path / "prices"
    divs = tmp_path / "divs"
    _write_prices(
        prices / "MTSS.csv",
        [{"date": f"2018-{m:02d}-15", "close": 100.0} for m in range(1, 13)],
    )
    _write_divs(divs / "MTSS.csv", [])
    gaps = compute_gaps(prices, divs)
    assert gaps == [{"ticker": "MTSS", "year": 2018, "reason": "no_record_for_year"}]


def test_compute_gaps_skips_short_year(tmp_path: Path) -> None:
    prices = tmp_path / "prices"
    divs = tmp_path / "divs"
    _write_prices(
        prices / "FOO.csv",
        [{"date": f"2024-{m:02d}-15", "close": 100.0} for m in (1, 2, 3, 4, 5)],
    )
    _write_divs(divs / "FOO.csv", [])
    assert compute_gaps(prices, divs) == []


def test_compute_gaps_respects_acked(tmp_path: Path) -> None:
    prices = tmp_path / "prices"
    divs = tmp_path / "divs"
    _write_prices(
        prices / "FOO.csv",
        [{"date": f"2018-{m:02d}-15", "close": 100.0} for m in range(1, 13)],
    )
    _write_divs(divs / "FOO.csv", [])
    assert compute_gaps(prices, divs, acked={"FOO": {2018}}) == []


def test_compute_gaps_year_with_div_not_flagged(tmp_path: Path) -> None:
    prices = tmp_path / "prices"
    divs = tmp_path / "divs"
    _write_prices(
        prices / "SBER.csv",
        [{"date": f"2024-{m:02d}-15", "close": 100.0} for m in range(1, 13)],
    )
    _write_divs(
        divs / "SBER.csv",
        [
            {
                "registry_close": "2024-07-11",
                "amount": 33.3,
                "currency": "RUB",
                "source": "moex_iss",
            }
        ],
    )
    assert compute_gaps(prices, divs) == []


def test_load_acked_reads_dict_schema(tmp_path: Path) -> None:
    p = tmp_path / "_acked.json"
    p.write_text(
        json.dumps({"foo": {"2018": "no div per company report", "2019": "x"}}),
        encoding="utf-8",
    )
    out = load_acked(p)
    assert out == {"FOO": {2018, 2019}}


def test_load_acked_missing_returns_empty(tmp_path: Path) -> None:
    assert load_acked(tmp_path / "absent.json") == {}


def test_load_acked_rejects_non_dict(tmp_path: Path) -> None:
    p = tmp_path / "_acked.json"
    p.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        load_acked(p)


def test_save_gaps_writes_pretty_json(tmp_path: Path) -> None:
    p = tmp_path / "_gaps.json"
    save_gaps(p, [{"ticker": "X", "year": 2020, "reason": "no_record_for_year"}])
    text = p.read_text(encoding="utf-8")
    assert "\n  " in text
    assert json.loads(text) == [{"ticker": "X", "year": 2020, "reason": "no_record_for_year"}]
