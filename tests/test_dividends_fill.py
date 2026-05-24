"""Tests for dividend fill (predecessor cutoff, multi-tier fill driver, fetchers,
fuzzy dedup, conflict resolution)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ingest.dividends.conflicts import (
    _load_conflicts,
    apply_conflicts_to_jsonl,
    apply_conflicts_to_universe,
)
from ingest.dividends.dohod import DohodFetcher
from ingest.dividends.fill import fill_dividends, predecessor_cutoff
from ingest.dividends.merge import cleanup_jsonl_near_duplicates, dedup_near_duplicates
from storage.records import read_records, write_records_atomic
from storage.schemas import DIV_CASTS, DIV_FIELDS, PRICE_FIELDS


def _write(path: Path, records: list[dict[str, Any]]) -> None:
    """Helper: write a CSV file using the relevant schema based on the path."""
    # Most callers seed dividend records; one seed (EPLN.csv) is empty.
    if records and "registry_close" in records[0]:
        write_records_atomic(path, records, fieldnames=DIV_FIELDS)
    elif records and "date" in records[0]:
        write_records_atomic(path, records, fieldnames=PRICE_FIELDS)
    else:
        # Empty seed — pick by directory name.
        parent = path.parent.name
        if parent == "d":
            write_records_atomic(path, [], fieldnames=DIV_FIELDS)
        else:
            write_records_atomic(path, [], fieldnames=PRICE_FIELDS)


def test_predecessor_cutoff_from_manual(tmp_path: Path) -> None:
    tickers = {"X5": {"canonical": "X5", "type": "share", "history": []}}
    manual = [
        {
            "old_secid": "FIVE",
            "new_secid": "X5",
            "renamed": "2025-01-09",
            "type": "redomicile",
            "reason": "...",
        },
    ]
    cutoff = predecessor_cutoff(
        "X5",
        tickers_dict=tickers,
        tickers_manual=manual,
        prices_dir=tmp_path / "p",
        dividends_dir=tmp_path / "d",
    )
    assert cutoff == "2025-01-09"


def test_predecessor_cutoff_polymetal_marker_ignored(tmp_path: Path) -> None:
    tickers = {"POLY": {"canonical": "POLY", "type": "share", "history": []}}
    manual = [
        {
            "old_secid": "POLY",
            "new_secid": "POLY",
            "renamed": "2024-10-15",
            "type": "redomicile",
            "reason": "delisting marker",
        }
    ]
    assert (
        predecessor_cutoff(
            "POLY",
            tickers_dict=tickers,
            tickers_manual=manual,
            prices_dir=tmp_path / "p",
            dividends_dir=tmp_path / "d",
        )
        is None
    )


def test_predecessor_cutoff_iss_changeover_ignored(tmp_path: Path) -> None:
    """SFIN←EPLN was a short-gap SECID rename (5 days), same company.
    Policy: bridge — iss_changeover never triggers cutoff."""
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "EPLN.csv").write_text("")
    tickers = {
        "SFIN": {
            "history": [
                {"prev_ticker": "EPLN", "renamed": "2018-01-03", "source": "iss_changeover"}
            ]
        }
    }
    assert (
        predecessor_cutoff(
            "SFIN",
            tickers_dict=tickers,
            tickers_manual=[],
            prices_dir=tmp_path / "p",
            dividends_dir=tmp_path / "d",
        )
        is None
    )


def test_predecessor_cutoff_manual_wins_even_with_changeover(tmp_path: Path) -> None:
    """VKCO has both an iss_changeover entry and a manual redomicile —
    manual wins because the entity changed legally (NL→RU MKPAO)."""
    tickers = {
        "VKCO": {
            "history": [
                {"prev_ticker": "MAIL", "renamed": "2021-12-13", "source": "iss_changeover"}
            ]
        }
    }
    manual = [
        {
            "old_secid": "MAIL",
            "new_secid": "VKCO",
            "renamed": "2021-10-12",
            "type": "redomicile",
            "reason": "NL→RU redomicile",
        }
    ]
    assert (
        predecessor_cutoff(
            "VKCO",
            tickers_dict=tickers,
            tickers_manual=manual,
            prices_dir=tmp_path / "p",
            dividends_dir=tmp_path / "d",
        )
        == "2021-10-12"
    )


class _StubFetcher:
    def __init__(self, tag: str, records: list[dict[str, Any]]) -> None:
        self.source_tag = tag
        self._records = records

    def fetch(self, ticker: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self._records]


def test_fill_dividends_basic_merge(tmp_path: Path) -> None:
    div_dir = tmp_path / "d"
    div_dir.mkdir()
    _write(
        div_dir / "MTSS.csv",
        [
            {
                "registry_close": "2024-07-08",
                "amount": 35.0,
                "currency": "RUB",
                "source": "moex_iss",
            },
        ],
    )
    dohod = _StubFetcher(
        "skill_fill_dohod",
        [
            {
                "registry_close": "2010-05-10",
                "amount": 15.4,
                "currency": "RUB",
                "source": "skill_fill_dohod",
            },
            {
                "registry_close": "2024-07-08",
                "amount": 35.0,
                "currency": "RUB",
                "source": "skill_fill_dohod",
            },
        ],
    )
    result = fill_dividends(
        "MTSS",
        fetchers=[dohod],
        tickers_dict={},
        tickers_manual=[],
        prices_dir=tmp_path / "p",
        dividends_dir=div_dir,
    )
    assert result.n_new == 1
    assert result.by_source["skill_fill_dohod"] == 1
    assert result.cutoff is None


def test_fill_dividends_predecessor_cutoff_drops(tmp_path: Path) -> None:
    """Manual redomicile (X5←FIVE) drops pre-cutoff records."""
    div_dir = tmp_path / "d"
    div_dir.mkdir()
    manual = [
        {
            "old_secid": "FIVE",
            "new_secid": "X5",
            "renamed": "2025-01-09",
            "type": "redomicile",
            "reason": "...",
        }
    ]
    dohod = _StubFetcher(
        "skill_fill_dohod",
        [
            {
                "registry_close": "2020-05-01",
                "amount": 184.13,
                "currency": "RUB",
                "source": "skill_fill_dohod",
            },
            {
                "registry_close": "2025-07-09",
                "amount": 648.0,
                "currency": "RUB",
                "source": "skill_fill_dohod",
            },
        ],
    )
    result = fill_dividends(
        "X5",
        fetchers=[dohod],
        tickers_dict={},
        tickers_manual=manual,
        prices_dir=tmp_path / "p",
        dividends_dir=div_dir,
    )
    assert result.cutoff == "2025-01-09"
    assert result.n_pre_cutoff_dropped == 1
    assert result.n_new == 1
    assert result.by_source["skill_fill_dohod"] == 1


def test_fill_dividends_tier_priority(tmp_path: Path) -> None:
    div_dir = tmp_path / "d"
    div_dir.mkdir()
    _write(div_dir / "T.csv", [])
    dohod = _StubFetcher(
        "skill_fill_dohod",
        [
            {
                "registry_close": "2020-05-01",
                "amount": 1.0,
                "currency": "RUB",
                "source": "skill_fill_dohod",
            },
        ],
    )
    yahoo = _StubFetcher(
        "skill_fill_yahoo",
        [
            {
                "registry_close": "2020-05-01",
                "amount": 1.0,
                "currency": "RUB",
                "source": "skill_fill_yahoo",
            },
            {
                "registry_close": "2021-06-15",
                "amount": 2.5,
                "currency": "RUB",
                "source": "skill_fill_yahoo",
            },
        ],
    )
    result = fill_dividends(
        "T",
        fetchers=[dohod, yahoo],
        tickers_dict={},
        tickers_manual=[],
        prices_dir=tmp_path / "p",
        dividends_dir=div_dir,
    )
    assert result.n_new == 2
    assert result.by_source["skill_fill_dohod"] == 1
    assert result.by_source["skill_fill_yahoo"] == 1


def test_fill_dividends_fetcher_exception_isolated(tmp_path: Path) -> None:
    div_dir = tmp_path / "d"
    div_dir.mkdir()
    _write(div_dir / "AAA.csv", [])

    class Boom:
        source_tag = "skill_fill_dohod"

        def fetch(self, ticker: str) -> list[dict[str, Any]]:
            raise RuntimeError("network down")

    yahoo = _StubFetcher(
        "skill_fill_yahoo",
        [
            {
                "registry_close": "2020-05-01",
                "amount": 1.0,
                "currency": "RUB",
                "source": "skill_fill_yahoo",
            },
        ],
    )
    result = fill_dividends(
        "AAA",
        fetchers=[Boom(), yahoo],
        tickers_dict={},
        tickers_manual=[],
        prices_dir=tmp_path / "p",
        dividends_dir=div_dir,
    )
    assert result.n_new == 1
    assert result.by_source.get("skill_fill_dohod", 0) == 0
    assert result.by_source["skill_fill_yahoo"] == 1


# ---------- DohodFetcher ----------


SAMPLE_DOHOD_HTML = """
<html><body>
<table><tr><td>summary</td></tr></table>
<table><tr><td>year-summary</td></tr></table>
<table>
  <tr><th>Дата объявления дивиденда</th><th>Дата закрытия реестра</th>
      <th>Год для учета дивиденда</th><th>Дивиденд</th></tr>
  <tr><td>n/a</td><td>07.07.2026 (прогноз)</td><td>n/a</td><td>35.0</td></tr>
  <tr><td>20.05.2025</td><td>07.07.2025</td><td>2025</td><td>35.0</td></tr>
  <tr><td>25.06.2004</td><td>01.07.2004</td><td>2004</td><td>3.2</td></tr>
</table>
</body></html>
"""


def test_dohod_fetcher_parses_table_2(tmp_path: Path) -> None:
    def http_get(url: str) -> str:
        return SAMPLE_DOHOD_HTML

    f = DohodFetcher(http_get, cache_dir=tmp_path)
    rows = f.fetch("MTSS")
    assert len(rows) == 2  # forecast dropped
    assert rows[0]["registry_close"] == "2025-07-07"
    assert rows[0]["amount"] == 35.0
    assert rows[1]["registry_close"] == "2004-07-01"
    assert (tmp_path / "dohod" / "mtss.html").exists()


def test_dohod_fetcher_uses_cache(tmp_path: Path) -> None:
    cache = tmp_path / "dohod"
    cache.mkdir()
    (cache / "mtss.html").write_text(SAMPLE_DOHOD_HTML, encoding="utf-8")
    calls: list[str] = []

    def http_get(url: str) -> str:
        calls.append(url)
        return ""

    f = DohodFetcher(http_get, cache_dir=tmp_path)
    rows = f.fetch("MTSS")
    assert len(rows) == 2
    assert calls == []


# ---------- Conflict resolution ----------


def test_apply_replace_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "MTLRP.csv"
    _write(
        path,
        [
            {
                "registry_close": "2017-07-11",
                "amount": 5.14,
                "currency": "RUB",
                "source": "moex_iss",
            },
            {
                "registry_close": "2020-06-30",
                "amount": 11.41,
                "currency": "RUB",
                "source": "moex_iss",
            },
        ],
    )
    conflicts = [
        {
            "ticker": "MTLRP",
            "registry_close": "2017-07-11",
            "action": "replace",
            "from": {"amount": 5.14, "source": "moex_iss"},
            "to": {"amount": 10.28, "source": "skill_fill_dohod", "currency": "RUB"},
            "reason": "ISS stale half-figure",
        }
    ]
    r1 = apply_conflicts_to_jsonl(path, conflicts)
    assert r1.applied == 1
    recs = read_records(path, casts=DIV_CASTS)
    assert any(r["amount"] == 10.28 and r["source"] == "skill_fill_dohod" for r in recs)
    assert not any(r["amount"] == 5.14 for r in recs)
    r2 = apply_conflicts_to_jsonl(path, conflicts)
    assert r2.applied == 0
    assert r2.skipped_no_match == 1


def test_apply_drop(tmp_path: Path) -> None:
    path = tmp_path / "SFIN.csv"
    _write(
        path,
        [
            {
                "registry_close": "2024-06-17",
                "amount": 20.6,
                "currency": "RUB",
                "source": "moex_iss",
            },
            {
                "registry_close": "2024-11-30",
                "amount": 113.8,
                "currency": "RUB",
                "source": "moex_iss",
            },
            {
                "registry_close": "2024-12-23",
                "amount": 227.6,
                "currency": "RUB",
                "source": "moex_iss",
            },
        ],
    )
    conflicts = [
        {
            "ticker": "SFIN",
            "registry_close": "2024-11-30",
            "action": "drop",
            "match": {"amount": 113.8, "source": "moex_iss"},
            "reason": "Stale pre-approval recommendation",
        }
    ]
    r = apply_conflicts_to_jsonl(path, conflicts)
    assert r.applied == 1
    recs = read_records(path, casts=DIV_CASTS)
    assert len(recs) == 2
    assert not any(r["amount"] == 113.8 for r in recs)


def test_apply_conflicts_skips_other_tickers(tmp_path: Path) -> None:
    path = tmp_path / "AAA.csv"
    _write(
        path,
        [{"registry_close": "2024-01-01", "amount": 1.0, "currency": "RUB", "source": "moex_iss"}],
    )
    conflicts = [
        {
            "ticker": "BBB",
            "registry_close": "2024-01-01",
            "action": "replace",
            "from": {"amount": 1.0, "source": "moex_iss"},
            "to": {"amount": 2.0, "source": "skill_fill_dohod", "currency": "RUB"},
            "reason": "irrelevant",
        }
    ]
    r = apply_conflicts_to_jsonl(path, conflicts)
    assert r.applied == 0


def test_load_conflicts_validates(tmp_path: Path) -> None:
    p = tmp_path / "c.json"
    p.write_text('[{"ticker":"X","registry_close":"2024-01-01","action":"bogus","reason":"x"}]')
    with pytest.raises(ValueError, match="action="):
        _load_conflicts(p)
    p.write_text('[{"ticker":"X","registry_close":"2024-01-01","action":"replace","reason":"x"}]')
    with pytest.raises(ValueError, match="replace requires"):
        _load_conflicts(p)


def test_apply_universe(tmp_path: Path) -> None:
    div_dir = tmp_path / "d"
    div_dir.mkdir()
    _write(
        div_dir / "MTLRP.csv",
        [
            {
                "registry_close": "2017-07-11",
                "amount": 5.14,
                "currency": "RUB",
                "source": "moex_iss",
            },
        ],
    )
    _write(
        div_dir / "SFIN.csv",
        [
            {
                "registry_close": "2024-11-30",
                "amount": 113.8,
                "currency": "RUB",
                "source": "moex_iss",
            },
            {
                "registry_close": "2024-12-23",
                "amount": 227.6,
                "currency": "RUB",
                "source": "moex_iss",
            },
        ],
    )
    confs = tmp_path / "c.json"
    confs.write_text(
        json.dumps(
            [
                {
                    "ticker": "MTLRP",
                    "registry_close": "2017-07-11",
                    "action": "replace",
                    "from": {"amount": 5.14, "source": "moex_iss"},
                    "to": {"amount": 10.28, "source": "skill_fill_dohod", "currency": "RUB"},
                    "reason": "stale",
                },
                {
                    "ticker": "SFIN",
                    "registry_close": "2024-11-30",
                    "action": "drop",
                    "match": {"amount": 113.8, "source": "moex_iss"},
                    "reason": "stale",
                },
            ]
        )
    )
    results = apply_conflicts_to_universe(div_dir, confs)
    assert results["MTLRP"].applied == 1
    assert results["SFIN"].applied == 1


# ---------- Fuzzy near-duplicate ----------


def test_dedup_near_duplicates_collapses_same_payout() -> None:
    """3 sources, same payout, slightly different date/amount → ISS wins."""
    rows = [
        {
            "registry_close": "2023-06-03",
            "amount": 564.0,
            "currency": "RUB",
            "source": "skill_fill_yahoo",
        },
        {"registry_close": "2023-06-05", "amount": 563.77, "currency": "RUB", "source": "moex_iss"},
        {
            "registry_close": "2023-06-05",
            "amount": 563.8,
            "currency": "RUB",
            "source": "skill_fill_dohod",
        },
    ]
    kept, dropped = dedup_near_duplicates(rows)
    assert len(kept) == 1
    assert kept[0]["source"] == "moex_iss"
    assert kept[0]["amount"] == 563.77
    assert len(dropped) == 2


def test_dedup_near_duplicates_preserves_real_two_tranche() -> None:
    """Two real tranches close in time but with materially different amounts
    must both survive."""
    rows = [
        {"registry_close": "2021-05-17", "amount": 22.51, "currency": "RUB", "source": "moex_iss"},
        {
            "registry_close": "2021-05-17",
            "amount": 22.92,
            "currency": "RUB",
            "source": "skill_fill_dohod",
        },
    ]
    kept, dropped = dedup_near_duplicates(rows)
    assert len(kept) == 2
    assert dropped == []


def test_dedup_near_duplicates_currency_isolated() -> None:
    """RUB and USD on the same date with same numeric amount must not collapse."""
    rows = [
        {"registry_close": "2024-05-01", "amount": 100.0, "currency": "RUB", "source": "moex_iss"},
        {
            "registry_close": "2024-05-01",
            "amount": 100.0,
            "currency": "USD",
            "source": "skill_fill_dohod",
        },
    ]
    kept, _ = dedup_near_duplicates(rows)
    assert len(kept) == 2


def test_dedup_near_duplicates_far_dates_keeps_both() -> None:
    rows = [
        {"registry_close": "2024-01-01", "amount": 5.0, "currency": "RUB", "source": "moex_iss"},
        {
            "registry_close": "2024-06-01",
            "amount": 5.0,
            "currency": "RUB",
            "source": "skill_fill_dohod",
        },
    ]
    kept, _ = dedup_near_duplicates(rows)
    assert len(kept) == 2


def test_cleanup_jsonl_writes_when_dups_found(tmp_path: Path) -> None:
    p = tmp_path / "VSMO.csv"
    _write(
        p,
        [
            {
                "registry_close": "2023-06-05",
                "amount": 563.77,
                "currency": "RUB",
                "source": "moex_iss",
            },
            {
                "registry_close": "2023-06-05",
                "amount": 563.8,
                "currency": "RUB",
                "source": "skill_fill_dohod",
            },
        ],
    )
    kept, dropped = cleanup_jsonl_near_duplicates(p)
    assert kept == 1 and dropped == 1
    recs = read_records(p, casts=DIV_CASTS)
    assert recs[0]["source"] == "moex_iss"


def test_fill_dividends_collapses_near_dup_against_iss(tmp_path: Path) -> None:
    """When ISS has the truth and dohod reports the same payout with slightly
    different date/amount, fill must not add the dohod record."""
    div_dir = tmp_path / "d"
    div_dir.mkdir()
    _write(
        div_dir / "VSMO.csv",
        [
            {
                "registry_close": "2023-06-05",
                "amount": 563.77,
                "currency": "RUB",
                "source": "moex_iss",
            },
        ],
    )
    dohod = _StubFetcher(
        "skill_fill_dohod",
        [
            {
                "registry_close": "2023-06-05",
                "amount": 563.8,
                "currency": "RUB",
                "source": "skill_fill_dohod",
            },
        ],
    )
    result = fill_dividends(
        "VSMO",
        fetchers=[dohod],
        tickers_dict={},
        tickers_manual=[],
        prices_dir=tmp_path / "p",
        dividends_dir=div_dir,
    )
    assert result.n_new == 0
    assert result.n_near_dup_dropped == 1
