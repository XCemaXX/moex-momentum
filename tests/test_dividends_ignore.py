from __future__ import annotations

import json
from pathlib import Path

import pytest

from ingest.dividends.conflicts import _load_conflicts, should_ignore_conflict


def _entry(**kw: object) -> dict[str, object]:
    base = {"ticker": "AKRN", "action": "ignore", "reason": "test"}
    base.update(kw)
    return base


def test_full_ticker_wildcard_matches() -> None:
    ignores = [
        _entry(
            match={"source": "skill_fill_yahoo"},
            applies_to_ym_pattern="*",
        )
    ]
    hit = should_ignore_conflict(
        ignores, ticker="AKRN", ym="2019-06", registry_close="2019-06-09", source="skill_fill_yahoo"
    )
    assert hit is not None


def test_source_mismatch_does_not_match() -> None:
    ignores = [
        _entry(
            match={"source": "skill_fill_yahoo"},
            applies_to_ym_pattern="*",
        )
    ]
    hit = should_ignore_conflict(
        ignores, ticker="AKRN", ym="2019-06", registry_close="2019-06-09", source="skill_fill_tbank"
    )
    assert hit is None


def test_ticker_mismatch_does_not_match() -> None:
    ignores = [_entry(applies_to_ym_pattern="*")]
    hit = should_ignore_conflict(
        ignores, ticker="GMKN", ym="2019-06", registry_close="2019-06-09", source="skill_fill_yahoo"
    )
    assert hit is None


def test_ym_pattern_specific_match() -> None:
    ignores = [
        _entry(
            ticker="MAGN",
            applies_to_ym_pattern="2016-06",
        )
    ]
    assert should_ignore_conflict(ignores, "MAGN", "2016-06", "2016-06-07", None) is not None
    assert should_ignore_conflict(ignores, "MAGN", "2017-06", "2017-06-07", None) is None


def test_specific_registry_close_match() -> None:
    ignores = [
        _entry(
            ticker="LKOH",
            registry_close="2013-08-15",
            match={"source": "skill_fill_yahoo"},
        )
    ]
    assert (
        should_ignore_conflict(ignores, "LKOH", "2013-08", "2013-08-15", "skill_fill_yahoo")
        is not None
    )
    assert (
        should_ignore_conflict(ignores, "LKOH", "2013-08", "2013-08-20", "skill_fill_yahoo") is None
    )


def test_no_source_filter_matches_any() -> None:
    ignores = [_entry(applies_to_ym_pattern="*")]
    assert should_ignore_conflict(ignores, "AKRN", "2019-06", "2019-06-09", "anything") is not None


def test_non_ignore_entries_skipped() -> None:
    ignores = [
        {
            "ticker": "AKRN",
            "action": "replace",
            "registry_close": "2019-06-09",
            "from": {"amount": 1, "source": "moex_iss"},
            "to": {"amount": 2, "currency": "RUB", "source": "manual_disclosure"},
            "reason": "test",
        }
    ]
    assert should_ignore_conflict(ignores, "AKRN", "2019-06", "2019-06-09", None) is None


def test_load_conflicts_accepts_ignore_without_registry_close(tmp_path: Path) -> None:
    p = tmp_path / "c.json"
    p.write_text(
        json.dumps(
            [
                {
                    "ticker": "AKRN",
                    "action": "ignore",
                    "reason": "test",
                    "applies_to_ym_pattern": "*",
                    "match": {"source": "skill_fill_yahoo"},
                }
            ]
        ),
        encoding="utf-8",
    )
    loaded = _load_conflicts(p)
    assert len(loaded) == 1
    assert loaded[0]["action"] == "ignore"


def test_load_conflicts_rejects_non_ignore_without_registry_close(tmp_path: Path) -> None:
    p = tmp_path / "c.json"
    p.write_text(
        json.dumps(
            [
                {
                    "ticker": "AKRN",
                    "action": "drop",
                    "reason": "test",
                    "match": {"amount": 1, "source": "moex_iss"},
                }
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="registry_close"):
        _load_conflicts(p)
