"""Tests for corporate-action detector: thresholds, suppressors, ack window."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from adjustments.detect import _is_sustained_rebase, _prices_to_df, detect_suspicious, load_acked
from config import SPLIT_MATCH_DAYS
from storage.records import read_records
from storage.schemas import PRICE_CASTS, SPLIT_CASTS
from tests.conftest import DATA_DIR


def _price_series(rows: list[tuple[str, float, float]]) -> list[dict[str, Any]]:
    return [{"date": d, "close": c, "value": v} for d, c, v in rows]


def test_detect_flags_obvious_split() -> None:
    """No split record → -99% return on big-volume day must flag."""
    prices = _price_series(
        [
            ("2024-07-12", 100.0, 10_000_000),
            ("2024-07-15", 0.02, 8_500_000_000),
            ("2024-07-16", 0.025, 5_000_000_000),
        ]
    )
    out = detect_suspicious("VTBR", prices, [], [], [])
    assert len(out) == 1
    assert out[0].date == "2024-07-15"
    assert out[0].raw_return < -0.9
    # Three rows are too short to judge a plateau, so it lands in the catch-all
    # rather than the split queue — the flag itself is what this test pins.
    assert out[0].reason == "limit_move"


def test_detect_suppresses_known_split() -> None:
    prices = _price_series(
        [
            ("2024-07-12", 100.0, 10_000_000),
            ("2024-07-15", 0.02, 8_500_000_000),
        ]
    )
    splits = [
        {
            "date": "2024-07-15",
            "before": 5000,
            "after": 1,
            "type": "reverse",
            "source": "moex_iss",
        }
    ]
    assert detect_suspicious("VTBR", prices, [], splits, []) == []


def test_detect_suppresses_split_within_one_trading_day() -> None:
    prices = _price_series(
        [
            ("2024-07-12", 100.0, 10_000_000),
            ("2024-07-15", 0.02, 8_500_000_000),
            ("2024-07-16", 0.025, 5_000_000_000),
        ]
    )
    splits = [
        {
            "date": "2024-07-12",
            "before": 5000,
            "after": 1,
            "type": "reverse",
            "source": "moex_iss",
        }
    ]
    assert detect_suspicious("VTBR", prices, [], splits, []) == []


def test_detect_suppresses_dividend_ex_date() -> None:
    prices = _price_series(
        [
            ("2024-07-10", 100.0, 10_000_000),
            ("2024-07-11", 60.0, 10_000_000),
        ]
    )
    divs = [
        {"registry_close": "2024-07-11", "amount": 33.3, "currency": "RUB", "source": "moex_iss"}
    ]
    assert detect_suspicious("X", prices, divs, [], []) == []


def test_detect_dividend_one_day_off_does_not_suppress() -> None:
    """Dividends match by exact ex-date only — no ±1 window for divs."""
    prices = _price_series(
        [
            ("2024-07-10", 100.0, 10_000_000),
            ("2024-07-11", 60.0, 10_000_000),
        ]
    )
    divs = [
        {"registry_close": "2024-07-12", "amount": 33.3, "currency": "RUB", "source": "moex_iss"}
    ]
    assert len(detect_suspicious("X", prices, divs, [], [])) == 1


def test_detect_acked_suppresses() -> None:
    prices = _price_series(
        [
            ("2022-02-23", 100.0, 50_000_000),
            ("2022-02-24", 30.0, 50_000_000),
        ]
    )
    assert detect_suspicious("POLY", prices, [], [], ["2022-02-24"]) == []


def test_detect_value_floor_kills_pennies() -> None:
    """Single-trade penny day at low turnover must NOT flag."""
    prices = _price_series(
        [
            ("2024-01-08", 100.0, 50_000_000),
            ("2024-01-09", 200.0, 50_000),  # 1% threshold of value
        ]
    )
    assert detect_suspicious("PENNY", prices, [], [], []) == []


def test_detect_threshold_below_does_not_flag() -> None:
    prices = _price_series(
        [
            ("2024-01-08", 100.0, 50_000_000),
            ("2024-01-09", 125.0, 50_000_000),  # +25%, below 30% default
        ]
    )
    assert detect_suspicious("X", prices, [], [], []) == []


def test_detect_threshold_above_flags() -> None:
    prices = _price_series(
        [
            ("2024-01-08", 100.0, 50_000_000),
            ("2024-01-09", 135.0, 50_000_000),  # +35%
        ]
    )
    assert len(detect_suspicious("X", prices, [], [], [])) == 1


def test_detect_drops_zero_close_rows() -> None:
    """close=0 in pre-2010 ISS → would yield +inf return; must be filtered out."""
    prices = _price_series(
        [
            ("2008-01-08", 0.0, 50_000_000),
            ("2008-01-09", 100.0, 50_000_000),
            ("2008-01-10", 105.0, 50_000_000),
        ]
    )
    out = detect_suspicious("X", prices, [], [], [])
    assert out == []


def test_detect_short_history_returns_empty() -> None:
    prices = _price_series([("2024-01-08", 100.0, 50_000_000)])
    assert detect_suspicious("X", prices, [], [], []) == []


def test_load_acked_parses_list(tmp_path: Path) -> None:
    p = tmp_path / "_acked.json"
    p.write_text(
        json.dumps(
            [
                {"ticker": "POLY", "date": "2022-02-24", "comment": "war shock"},
                {"ticker": "poly", "date": "2022-03-01", "comment": "x"},
            ]
        ),
        encoding="utf-8",
    )
    out = load_acked(p)
    assert out == {"POLY": ["2022-02-24", "2022-03-01"]}


def test_load_acked_missing_returns_empty(tmp_path: Path) -> None:
    assert load_acked(tmp_path / "absent.json") == {}


def test_load_acked_rejects_object(tmp_path: Path) -> None:
    p = tmp_path / "_acked.json"
    p.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON array"):
        load_acked(p)


def test_known_splits_are_classified_as_rebase() -> None:
    """Recall pin on the confirmed corporate actions in `data/splits/`.

    Calibration is worth only what it catches: a threshold tightened for a
    shorter triage queue must fail here rather than silently drop an event.
    A recorded date is not always a trading day, hence the window.
    """
    missed: list[str] = []
    for splits_path in sorted((DATA_DIR / "splits").glob("*.csv")):
        ticker = splits_path.stem
        prices = read_records(DATA_DIR / "prices_iss" / f"{ticker}.csv", casts=PRICE_CASTS)
        df = _prices_to_df(prices)
        for rec in read_records(splits_path, casts=SPLIT_CASTS):
            target = pd.Timestamp(str(rec["date"]))
            near = [
                i for i, ts in enumerate(df.index) if abs((ts - target).days) <= SPLIT_MATCH_DAYS
            ]
            if not any(_is_sustained_rebase(df, i) for i in near):
                missed.append(f"{ticker} {rec['date']}")
    assert not missed, f"confirmed splits the classifier no longer detects: {missed}"


def test_board_change_is_not_a_split_candidate() -> None:
    """A price step that comes with a board switch is a source artefact."""
    prices = [
        {"date": f"2024-01-{d:02d}", "close": 100.0, "value": 1e9, "board": "TQBR"}
        for d in range(1, 11)
    ] + [
        {"date": f"2024-02-{d:02d}", "close": 40.0, "value": 1e9, "board": "SMAL"}
        for d in range(1, 11)
    ]
    flags = detect_suspicious("X", prices, [], [], [])
    assert [f.reason for f in flags] == ["board_change"]
