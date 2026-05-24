"""Tests for ISS dividend ingest."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest

from ingest.dividends import iss as div_mod
from ingest.dividends.iss import (
    _merge,
    _normalise_currency,
    _pivot_dividends,
    ingest,
    ingest_one,
)
from storage.records import read_records, write_records_atomic
from storage.schemas import DIV_CASTS, DIV_FIELDS

DIV_COLS = ["secid", "isin", "registryclosedate", "value", "currencyid"]


def _payload(rows: list[list[Any]], total: int | None = None) -> dict[str, Any]:
    return {
        "dividends": {"columns": DIV_COLS, "data": rows},
        "dividends.cursor": {
            "columns": ["INDEX", "TOTAL", "PAGESIZE"],
            "data": [[0, total if total is not None else len(rows), 100]],
        },
    }


def _make_client(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="https://iss.moex.com/iss",
        transport=httpx.MockTransport(handler),
    )


# ---------- pivot ----------


def test_pivot_basic() -> None:
    rows = _pivot_dividends(
        DIV_COLS,
        [
            ["SBER", "RU0009029540", "2024-07-11", 33.3, "RUB"],
            ["SBER", "RU0009029540", "2023-05-08", 25.0, "RUB"],
        ],
    )
    assert rows == [
        {"registry_close": "2024-07-11", "amount": 33.3, "currency": "RUB", "source": "moex_iss"},
        {"registry_close": "2023-05-08", "amount": 25.0, "currency": "RUB", "source": "moex_iss"},
    ]


def test_pivot_drops_null_value() -> None:
    rows = _pivot_dividends(
        DIV_COLS,
        [
            ["X", "RUX", "2020-01-01", None, "RUB"],
            ["X", "RUX", "2020-06-01", 10.0, "RUB"],
        ],
    )
    assert len(rows) == 1
    assert rows[0]["registry_close"] == "2020-06-01"


def test_pivot_drops_zero_value() -> None:
    rows = _pivot_dividends(DIV_COLS, [["X", "RUX", "2020-01-01", 0, "RUB"]])
    assert rows == []


def test_pivot_normalises_sur_to_rub() -> None:
    rows = _pivot_dividends(DIV_COLS, [["LEGACY", "RU", "2008-05-15", 5.0, "SUR"]])
    assert rows[0]["currency"] == "RUB"


def test_normalise_currency() -> None:
    assert _normalise_currency("SUR") == "RUB"
    assert _normalise_currency("rub") == "RUB"
    assert _normalise_currency("USD") == "USD"


# ---------- merge / dedup ----------


def test_merge_dedups_by_triple() -> None:
    existing = [
        {"registry_close": "2024-07-11", "amount": 33.3, "currency": "RUB", "source": "moex_iss"}
    ]
    new = [
        {"registry_close": "2024-07-11", "amount": 33.3, "currency": "RUB", "source": "moex_iss"},
        {"registry_close": "2023-05-08", "amount": 25.0, "currency": "RUB", "source": "moex_iss"},
    ]
    merged = _merge(existing, new)
    assert len(merged) == 2
    assert merged[0]["registry_close"] == "2023-05-08"
    assert merged[1]["registry_close"] == "2024-07-11"


def test_merge_keeps_existing_on_tie() -> None:
    existing = [
        {
            "registry_close": "2024-07-11",
            "amount": 33.3,
            "currency": "RUB",
            "source": "manual_disclosure",
            "comment": "verified",
        }
    ]
    new = [
        {"registry_close": "2024-07-11", "amount": 33.3, "currency": "RUB", "source": "moex_iss"}
    ]
    merged = _merge(existing, new)
    assert len(merged) == 1
    assert merged[0]["source"] == "manual_disclosure"
    assert merged[0]["comment"] == "verified"


def test_merge_treats_different_amount_as_distinct() -> None:
    existing = [
        {"registry_close": "2024-07-11", "amount": 33.3, "currency": "RUB", "source": "moex_iss"}
    ]
    new = [
        {"registry_close": "2024-07-11", "amount": 18.0, "currency": "RUB", "source": "moex_iss"}
    ]
    merged = _merge(existing, new)
    assert len(merged) == 2


# ---------- ingest_one ----------


def test_ingest_one_simple(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_payload(
                [
                    ["SBER", "RU", "2024-07-11", 33.3, "RUB"],
                    ["SBER", "RU", "2023-05-08", 25.0, "RUB"],
                ]
            ),
        )

    async def run() -> None:
        async with _make_client(handler) as client:
            m = await ingest_one(client, "SBER", output_dir=tmp_path, cache_dir=None)
            assert m.rows == 2
            assert m.first == "2023-05-08"
            assert m.last == "2024-07-11"

    asyncio.run(run())
    out = tmp_path / "SBER.csv"
    rows = read_records(out, casts=DIV_CASTS)
    assert rows[1]["amount"] == 33.3


def test_ingest_one_idempotent(tmp_path: Path) -> None:
    out = tmp_path / "SBER.csv"
    write_records_atomic(
        out,
        [
            {
                "registry_close": "2023-05-08",
                "amount": 25.0,
                "currency": "RUB",
                "source": "moex_iss",
            }
        ],
        fieldnames=DIV_FIELDS,
    )
    mtime = out.stat().st_mtime_ns

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_payload([["SBER", "RU", "2023-05-08", 25.0, "RUB"]]),
        )

    async def run() -> None:
        async with _make_client(handler) as client:
            m = await ingest_one(client, "SBER", output_dir=tmp_path, cache_dir=None)
            assert m.rows == 1

    asyncio.run(run())
    assert out.stat().st_mtime_ns == mtime  # untouched


def test_ingest_one_empty_payload(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_payload([]))

    async def run() -> None:
        async with _make_client(handler) as client:
            m = await ingest_one(client, "FOO", output_dir=tmp_path, cache_dir=None)
            assert m.rows == 0
            assert m.first is None

    asyncio.run(run())
    assert not (tmp_path / "FOO.csv").exists()


def test_ingest_one_404_returns_empty(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={})

    async def run() -> None:
        async with _make_client(handler) as client:
            m = await ingest_one(client, "GHOST", output_dir=tmp_path, cache_dir=None)
            assert m.rows == 0

    asyncio.run(run())


def test_ingest_writes_cache(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    out = tmp_path / "out"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_payload([["SBER", "RU", "2024-07-11", 33.3, "RUB"]]),
        )

    async def run() -> None:
        async with _make_client(handler) as client:
            await ingest_one(client, "SBER", output_dir=out, cache_dir=cache)

    asyncio.run(run())
    cached = list(cache.rglob("*.json"))
    assert cached


def test_ingest_dispatcher(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_payload([["SBER", "RU", "2024-07-11", 33.3, "RUB"]]))

    monkeypatch.setattr(div_mod, "make_async_client", lambda: _make_client(handler))

    result = asyncio.run(
        ingest(
            {"SBER": {"canonical": "Сбербанк"}},
            output_dir=tmp_path,
            cache_dir=None,
        )
    )
    assert result["SBER"].rows == 1
