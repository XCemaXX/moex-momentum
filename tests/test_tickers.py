"""Tests for tickers.py — load/save/lookup/walk_history.

HTTP bootstrap (`momentum tickers refresh`) is tested in test_tickers_refresh.py
(added after the ISS schema is locked).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

import tickers


@pytest.fixture
def tickers_file(tmp_path: Path) -> Path:
    p = tmp_path / "tickers.json"
    payload = {
        "SBER": {
            "canonical": "Сбербанк",
            "aliases": ["Сбер", "Sberbank", "Сбербанк ао"],
            "type": "share",
            "boards": [
                {
                    "board": "TQBR",
                    "history_from": "2013-03-25",
                    "history_till": "2026-05-04",
                    "is_primary": True,
                }
            ],
            "history": [],
        },
        "T": {
            "canonical": "Т-Технологии",
            "aliases": ["TCS Group", "Тинькофф"],
            "type": "share",
            "boards": [
                {
                    "board": "TQBR",
                    "history_from": "2019-10-28",
                    "history_till": "2026-05-04",
                    "is_primary": True,
                }
            ],
            "history": [
                {
                    "prev_ticker": "TCSG",
                    "renamed": "2024-11-27",
                    "source": "iss_changeover",
                }
            ],
        },
        "POLY": {
            "canonical": "Полиметалл",
            "aliases": ["Polymetal"],
            "type": "share",
            "boards": [
                {
                    "board": "TQBR",
                    "history_from": "2014-06-17",
                    "history_till": "2024-10-15",
                    "is_primary": True,
                }
            ],
            "delisted_after": "2024-10-15",
            "history": [],
        },
    }
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return p


def test_load_save_roundtrip(tickers_file: Path, tmp_path: Path) -> None:
    data = tickers.load(tickers_file)
    out = tmp_path / "out.json"
    tickers.save(out, data)
    assert tickers.load(out) == data


def test_save_uses_sorted_keys_and_indent(tmp_path: Path) -> None:
    out = tmp_path / "t.json"
    tickers.save(out, {"ZZZ": {"canonical": "Z"}, "AAA": {"canonical": "A"}})
    text = out.read_text(encoding="utf-8")
    assert text.index('"AAA"') < text.index('"ZZZ"')
    assert "\n  " in text


def test_load_returns_empty_for_missing_file(tmp_path: Path) -> None:
    assert tickers.load(tmp_path / "absent.json") == {}


def test_load_rejects_non_object(tmp_path: Path) -> None:
    p = tmp_path / "t.json"
    p.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        tickers.load(p)


def test_invariants_pass(tickers_file: Path) -> None:
    tickers.validate_tickers(tickers.load(tickers_file))


def test_invariants_reject_lowercase_key() -> None:
    with pytest.raises(ValueError, match="uppercase"):
        tickers.validate_tickers({"sber": {"canonical": "Сбер"}})


def test_invariants_reject_empty_canonical() -> None:
    with pytest.raises(ValueError, match="canonical is empty"):
        tickers.validate_tickers({"SBER": {"canonical": ""}})


def test_invariants_reject_alias_eq_canonical() -> None:
    with pytest.raises(ValueError, match="matches canonical"):
        tickers.validate_tickers({"SBER": {"canonical": "Сбер", "aliases": ["Сбер"]}})


def test_invariants_reject_multiple_primary() -> None:
    bad = {
        "SBER": {
            "canonical": "Сбер",
            "boards": [
                {"board": "TQBR", "is_primary": True},
                {"board": "EQBR", "is_primary": True},
            ],
        }
    }
    with pytest.raises(ValueError, match="is_primary"):
        tickers.validate_tickers(bad)


def test_invariants_allow_zero_primary() -> None:
    tickers.validate_tickers({"LEGACY": {"canonical": "Легаси", "boards": [{"board": "EQBR"}]}})


def test_resolve_alias_case_insensitive(tickers_file: Path) -> None:
    t = tickers.load(tickers_file)
    assert tickers.resolve_alias(t, "сбер") == "SBER"
    assert tickers.resolve_alias(t, "TCS GROUP") == "T"
    assert tickers.resolve_alias(t, "Полиметалл") == "POLY"
    assert tickers.resolve_alias(t, "несуществующий") is None
    assert tickers.resolve_alias(t, "") is None


def test_resolve_alias_finds_canonical(tickers_file: Path) -> None:
    t = tickers.load(tickers_file)
    assert tickers.resolve_alias(t, "Сбербанк") == "SBER"


def test_walk_history_t_boundary(tickers_file: Path) -> None:
    t = tickers.load(tickers_file)
    assert tickers.walk_history(t, "T", "2024-01-01") == "TCSG"
    assert tickers.walk_history(t, "T", "2024-11-26") == "TCSG"
    assert tickers.walk_history(t, "T", "2024-11-27") == "T"
    assert tickers.walk_history(t, "T", "2025-01-01") == "T"


def test_walk_history_accepts_date_object(tickers_file: Path) -> None:
    t = tickers.load(tickers_file)
    assert tickers.walk_history(t, "T", date(2024, 1, 1)) == "TCSG"
    assert tickers.walk_history(t, "T", date(2025, 1, 1)) == "T"


def test_walk_history_unknown_ticker_returns_self(tickers_file: Path) -> None:
    t = tickers.load(tickers_file)
    assert tickers.walk_history(t, "ZZZZ", "2024-01-01") == "ZZZZ"


def test_walk_history_no_history_returns_self(tickers_file: Path) -> None:
    t = tickers.load(tickers_file)
    assert tickers.walk_history(t, "SBER", "2010-01-01") == "SBER"


def test_walk_history_chain_two_steps() -> None:
    t: tickers.TickersDict = {
        "C": {
            "canonical": "C",
            "history": [{"prev_ticker": "B", "renamed": "2024-06-01", "source": "manual"}],
        },
        "B": {
            "canonical": "B",
            "history": [{"prev_ticker": "A", "renamed": "2022-01-01", "source": "manual"}],
        },
    }
    assert tickers.walk_history(t, "C", "2024-07-01") == "C"
    assert tickers.walk_history(t, "C", "2024-05-31") == "B"
    assert tickers.walk_history(t, "C", "2021-12-31") == "A"


def test_get_canonical_uppercases(tickers_file: Path) -> None:
    t = tickers.load(tickers_file)
    assert tickers.get_canonical(t, "sber") == "Сбербанк"


def test_get_history_returns_copy(tickers_file: Path) -> None:
    t = tickers.load(tickers_file)
    h = tickers.get_history(t, "T")
    h.clear()
    assert len(tickers.get_history(t, "T")) == 1


def test_manual_load_ok(tmp_path: Path) -> None:
    p = tmp_path / "manual.json"
    p.write_text(
        json.dumps(
            [
                {
                    "old_secid": "YNDX",
                    "new_secid": "YDEX",
                    "renamed": "2024-07-08",
                    "type": "redomicile",
                    "reason": "NL→RU",
                },
                {
                    "old_secid": "BELU",
                    "new_secid": "BELU",
                    "renamed": "2024-08-20",
                    "type": "bonus_issue",
                    "ratio": 0.125,
                    "reason": "1:8 bonus issue",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    out = tickers.load_manual(p)
    assert len(out) == 2
    assert out[0]["new_secid"] == "YDEX"


def test_manual_load_empty_for_missing_file(tmp_path: Path) -> None:
    assert tickers.load_manual(tmp_path / "nope.json") == []


def test_manual_rejects_empty_reason(tmp_path: Path) -> None:
    p = tmp_path / "manual.json"
    p.write_text(
        json.dumps(
            [
                {
                    "old_secid": "X",
                    "new_secid": "Y",
                    "renamed": "2024-01-01",
                    "type": "redomicile",
                    "reason": "",
                }
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="reason"):
        tickers.load_manual(p)


def test_manual_rejects_invalid_type(tmp_path: Path) -> None:
    p = tmp_path / "manual.json"
    p.write_text(
        json.dumps(
            [
                {
                    "old_secid": "X",
                    "new_secid": "Y",
                    "renamed": "2024-01-01",
                    "type": "merger",
                    "reason": "x",
                }
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="type="):
        tickers.load_manual(p)


def test_manual_bonus_requires_ratio(tmp_path: Path) -> None:
    p = tmp_path / "manual.json"
    p.write_text(
        json.dumps(
            [
                {
                    "old_secid": "BELU",
                    "new_secid": "BELU",
                    "renamed": "2024-08-20",
                    "type": "bonus_issue",
                    "reason": "x",
                }
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="ratio"):
        tickers.load_manual(p)


def test_manual_rejects_non_array(tmp_path: Path) -> None:
    p = tmp_path / "manual.json"
    p.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON array"):
        tickers.load_manual(p)
