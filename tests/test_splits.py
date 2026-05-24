"""Tests for splits ingest: ISS pivot/filter, manual bonus conversion, idempotency."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from ingest import splits as splits_mod
from ingest.splits import (
    _is_equity_secid,
    _merge_records,
    _parse_iss,
    _parse_manual,
    _ratio_to_record,
    _split_type,
    ingest,
)
from storage.records import read_records, write_records_atomic
from storage.schemas import SPLIT_CASTS, SPLIT_FIELDS
from tickers import TickersDict


def _payload(rows: list[list[Any]]) -> dict[str, Any]:
    return {
        "splits": {
            "columns": ["tradedate", "secid", "before", "after"],
            "data": rows,
        }
    }


@pytest.fixture
def tickers() -> TickersDict:
    return {
        "VTBR": {"canonical": "ВТБ", "type": "share"},
        "TRNFP": {"canonical": "Транснефть-п", "type": "share"},
        "BELU": {"canonical": "Белуга", "type": "share"},
        "T": {"canonical": "Т-Технологии", "type": "share"},
        "FXRU": {"canonical": "FXRU ETF", "type": "etf"},
    }


def test_split_type_classifies() -> None:
    assert _split_type(1, 100) == "forward"
    assert _split_type(5000, 1) == "reverse"
    with pytest.raises(ValueError, match="no-op"):
        _split_type(1, 1)


def test_is_equity_secid_filters(tickers: TickersDict) -> None:
    assert _is_equity_secid("VTBR", tickers) is True
    assert _is_equity_secid("FXRU", tickers) is False  # type=etf
    assert _is_equity_secid("SBER-RM", tickers) is False
    assert _is_equity_secid("FIXP", tickers) is False
    assert _is_equity_secid("RU000A0JPGA0", tickers) is False
    assert _is_equity_secid("UNKNOWN", tickers) is False  # not in dict


def test_parse_iss_drops_etf_and_misc(tickers: TickersDict) -> None:
    payload = _payload(
        [
            ["2024-07-15", "VTBR", 5000, 1],
            ["2024-02-21", "TRNFP", 1, 100],
            ["2018-12-12", "FXRU", 10, 1],
            ["2021-04-12", "VTBB", 1, 10],
            ["2025-03-27", "PLZL", 1, 10],  # not in tickers fixture → drop
        ]
    )
    out = _parse_iss(payload, tickers)
    assert set(out) == {"VTBR", "TRNFP"}
    assert out["VTBR"][0] == {
        "date": "2024-07-15",
        "before": 5000,
        "after": 1,
        "type": "reverse",
        "source": "moex_iss",
    }
    assert out["TRNFP"][0]["type"] == "forward"


def test_ratio_to_record_bonus_issue_belu() -> None:
    rec = _ratio_to_record(
        {
            "old_secid": "BELU",
            "new_secid": "BELU",
            "renamed": "2024-08-20",
            "type": "bonus_issue",
            "ratio": 0.125,
            "reason": "1:8 bonus issue",
        }
    )
    assert rec == {
        "date": "2024-08-20",
        "before": 1,
        "after": 8,
        "type": "bonus_issue",
        "source": "manual_bonus_issue",
    }


def test_ratio_to_record_reverse_split_irao() -> None:
    rec = _ratio_to_record(
        {
            "old_secid": "IRAO",
            "new_secid": "IRAO",
            "renamed": "2015-01-20",
            "type": "reverse_split",
            "ratio": 100.0,
            "reason": "100:1 consolidation",
        }
    )
    assert rec == {
        "date": "2015-01-20",
        "before": 100,
        "after": 1,
        "type": "reverse_split",
        "source": "manual_reverse_split",
    }


def test_parse_manual_picks_up_reverse_split() -> None:
    out = _parse_manual(
        [
            {
                "old_secid": "IRAO",
                "new_secid": "IRAO",
                "renamed": "2015-01-20",
                "type": "reverse_split",
                "ratio": 100.0,
                "reason": "x",
            },
        ]
    )
    assert set(out) == {"IRAO"}
    assert out["IRAO"][0]["before"] == 100
    assert out["IRAO"][0]["after"] == 1
    assert out["IRAO"][0]["type"] == "reverse_split"


def test_parse_manual_picks_only_bonus_issues() -> None:
    out = _parse_manual(
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
                "reason": "x",
            },
        ]
    )
    assert set(out) == {"BELU"}
    assert out["BELU"][0]["before"] == 1
    assert out["BELU"][0]["after"] == 8


def test_parse_manual_rejects_changing_secid() -> None:
    with pytest.raises(ValueError, match="must not change"):
        _parse_manual(
            [
                {
                    "old_secid": "X",
                    "new_secid": "Y",
                    "renamed": "2024-01-01",
                    "type": "bonus_issue",
                    "ratio": 0.5,
                    "reason": "x",
                }
            ]
        )


def test_merge_records_dedups_and_overrides() -> None:
    existing = [
        {
            "date": "2024-07-15",
            "before": 5000,
            "after": 1,
            "type": "reverse",
            "source": "moex_iss",
        }
    ]
    iss = [
        {
            "date": "2024-07-15",
            "before": 5000,
            "after": 1,
            "type": "reverse",
            "source": "moex_iss",
        },
        {
            "date": "2024-02-21",
            "before": 1,
            "after": 100,
            "type": "forward",
            "source": "moex_iss",
        },
    ]
    manual = [
        {
            "date": "2024-08-20",
            "before": 1,
            "after": 8,
            "type": "bonus_issue",
            "source": "manual_bonus_issue",
        }
    ]
    merged = _merge_records(existing, iss, manual)
    assert [r["date"] for r in merged] == ["2024-02-21", "2024-07-15", "2024-08-20"]


def test_merge_manual_overrides_iss_on_equal_key() -> None:
    iss = [
        {
            "date": "2024-08-20",
            "before": 1,
            "after": 8,
            "type": "forward",
            "source": "moex_iss",
        }
    ]
    manual = [
        {
            "date": "2024-08-20",
            "before": 1,
            "after": 8,
            "type": "bonus_issue",
            "source": "manual_bonus_issue",
        }
    ]
    merged = _merge_records([], iss, manual)
    assert len(merged) == 1
    assert merged[0]["source"] == "manual_bonus_issue"


def test_ingest_writes_per_ticker(
    tmp_path: Path, tickers: TickersDict, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_payload(
                [
                    ["2024-07-15", "VTBR", 5000, 1],
                    ["2024-02-21", "TRNFP", 1, 100],
                ]
            ),
        )

    def fake_client() -> httpx.Client:
        return httpx.Client(
            base_url="https://iss.moex.com/iss",
            transport=httpx.MockTransport(handler),
        )

    monkeypatch.setattr(splits_mod, "make_client", fake_client)
    counts = ingest(tickers, [], output_dir=tmp_path, cache_dir=None)
    assert counts == {"TRNFP": 1, "VTBR": 1}
    vtbr = read_records(tmp_path / "VTBR.csv", casts=SPLIT_CASTS)[0]
    assert vtbr["before"] == 5000


def test_ingest_idempotent(
    tmp_path: Path, tickers: TickersDict, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "VTBR.csv"
    write_records_atomic(
        out,
        [
            {
                "date": "2024-07-15",
                "before": 5000,
                "after": 1,
                "type": "reverse",
                "source": "moex_iss",
            }
        ],
        fieldnames=SPLIT_FIELDS,
    )
    mtime = out.stat().st_mtime_ns

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_payload([["2024-07-15", "VTBR", 5000, 1]]))

    monkeypatch.setattr(
        splits_mod,
        "make_client",
        lambda: httpx.Client(
            base_url="https://iss.moex.com/iss", transport=httpx.MockTransport(handler)
        ),
    )
    ingest(tickers, [], output_dir=tmp_path, cache_dir=None)
    assert out.stat().st_mtime_ns == mtime  # untouched


def test_ingest_caches_payload(
    tmp_path: Path, tickers: TickersDict, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "cache"
    out = tmp_path / "out"
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json=_payload([["2024-07-15", "VTBR", 5000, 1]]))

    monkeypatch.setattr(
        splits_mod,
        "make_client",
        lambda: httpx.Client(
            base_url="https://iss.moex.com/iss", transport=httpx.MockTransport(handler)
        ),
    )
    ingest(tickers, [], output_dir=out, cache_dir=cache)
    ingest(tickers, [], output_dir=out, cache_dir=cache)
    assert len(calls) == 1  # second run hits cache
