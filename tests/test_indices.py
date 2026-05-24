"""Tests for MOEX index series ingest (MCFTRR)."""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest

from ingest import indices as indices_mod
from ingest.indices import ingest, ingest_one
from storage.records import read_records, write_records_atomic
from storage.schemas import INDEX_CASTS, INDEX_FIELDS

HISTORY_COLS = ["BOARDID", "SECID", "TRADEDATE", "OPEN", "LOW", "HIGH", "CLOSE", "VALUE"]


def _row(secid: str, d: str, close: float) -> list[Any]:
    return ["RTSI", secid, d, close, close, close, close, 0]


def _history_payload(rows: list[list[Any]], total: int | None = None) -> dict[str, Any]:
    return {
        "history": {"columns": HISTORY_COLS, "data": rows},
        "history.cursor": {
            "columns": ["INDEX", "TOTAL", "PAGESIZE"],
            "data": [[0, total if total is not None else len(rows), 100]],
        },
    }


def _make_client(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="https://iss.moex.com/iss",
        transport=httpx.MockTransport(handler),
    )


def test_ingest_one_simple(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json=_history_payload(
                [
                    _row("MCFTRR", "2024-03-13", 6851.42),
                    _row("MCFTRR", "2024-03-14", 6900.00),
                ]
            ),
        )

    async def run() -> None:
        async with _make_client(handler) as client:
            m = await ingest_one(
                client,
                "MCFTRR",
                output_dir=tmp_path,
                cache_dir=None,
                today=date(2024, 3, 14),
            )
            assert m.rows == 2
            assert m.first == "2024-03-13"
            assert m.last == "2024-03-14"

    asyncio.run(run())
    out = tmp_path / "MCFTRR.csv"
    rows = read_records(out, casts=INDEX_CASTS)
    assert rows == [
        {"date": "2024-03-13", "close": 6851.42},
        {"date": "2024-03-14", "close": 6900.0},
    ]


def test_ingest_one_idempotent(tmp_path: Path) -> None:
    out = tmp_path / "MCFTRR.csv"
    write_records_atomic(out, [{"date": "2024-03-13", "close": 6851.42}], fieldnames=INDEX_FIELDS)

    captured: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(dict(request.url.params))
        return httpx.Response(
            200,
            json=_history_payload([_row("MCFTRR", "2024-03-14", 6900.00)]),
        )

    async def run() -> None:
        async with _make_client(handler) as client:
            m = await ingest_one(
                client,
                "MCFTRR",
                output_dir=tmp_path,
                cache_dir=None,
                today=date(2024, 3, 14),
            )
            assert m.rows == 2

    asyncio.run(run())
    # Repeat call must request from = max+1d.
    assert captured[0]["from"] == "2024-03-14"


def test_ingest_one_no_new_data(tmp_path: Path) -> None:
    out = tmp_path / "MCFTRR.csv"
    write_records_atomic(out, [{"date": "2024-03-14", "close": 6900.0}], fieldnames=INDEX_FIELDS)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_history_payload([]))

    async def run() -> None:
        async with _make_client(handler) as client:
            m = await ingest_one(
                client,
                "MCFTRR",
                output_dir=tmp_path,
                cache_dir=None,
                today=date(2024, 3, 14),
            )
            assert m.rows == 1
            assert m.last == "2024-03-14"

    asyncio.run(run())


def test_ingest_one_overlap_raises(tmp_path: Path) -> None:
    out = tmp_path / "MCFTRR.csv"
    write_records_atomic(out, [{"date": "2024-03-13", "close": 6851.42}], fieldnames=INDEX_FIELDS)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_history_payload([_row("MCFTRR", "2024-03-13", 9999.99)]),
        )

    async def run() -> None:
        async with _make_client(handler) as client:
            with pytest.raises(ValueError, match="unexpected overlap"):
                await ingest_one(
                    client,
                    "MCFTRR",
                    output_dir=tmp_path,
                    cache_dir=None,
                    today=date(2024, 3, 14),
                )

    asyncio.run(run())


def test_ingest_one_pagination(tmp_path: Path) -> None:
    page_starts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        page_starts.append(params.get("start", "0"))
        if params.get("start") == "0":
            return httpx.Response(
                200,
                json={
                    "history": {
                        "columns": HISTORY_COLS,
                        "data": [_row("MCFTRR", "2024-03-13", 6851.42)],
                    },
                    "history.cursor": {
                        "columns": ["INDEX", "TOTAL", "PAGESIZE"],
                        "data": [[0, 2, 1]],
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "history": {
                    "columns": HISTORY_COLS,
                    "data": [_row("MCFTRR", "2024-03-14", 6900.00)],
                },
                "history.cursor": {
                    "columns": ["INDEX", "TOTAL", "PAGESIZE"],
                    "data": [[1, 2, 1]],
                },
            },
        )

    async def run() -> None:
        async with _make_client(handler) as client:
            m = await ingest_one(
                client,
                "MCFTRR",
                output_dir=tmp_path,
                cache_dir=None,
                today=date(2024, 3, 14),
            )
            assert m.rows == 2

    asyncio.run(run())
    assert page_starts == ["0", "1"]


def test_ingest_one_skips_null_close(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_history_payload(
                [
                    ["RTSI", "MCFTRR", "2024-03-13", None, None, None, None, 0],
                    _row("MCFTRR", "2024-03-14", 6900.0),
                ]
            ),
        )

    async def run() -> None:
        async with _make_client(handler) as client:
            m = await ingest_one(
                client,
                "MCFTRR",
                output_dir=tmp_path,
                cache_dir=None,
                today=date(2024, 3, 14),
            )
            assert m.rows == 1
            assert m.first == "2024-03-14"

    asyncio.run(run())


def test_ingest_writes_cache(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    out = tmp_path / "out"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_history_payload([_row("MCFTRR", "2024-03-13", 6851.42)]),
        )

    async def run() -> None:
        async with _make_client(handler) as client:
            await ingest_one(
                client,
                "MCFTRR",
                output_dir=out,
                cache_dir=cache,
                today=date(2024, 3, 13),
            )

    asyncio.run(run())
    cached = list(cache.rglob("*.json"))
    assert cached, "cache should have at least one page"


def test_ingest_dispatcher(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_history_payload([_row("MCFTRR", "2024-03-13", 6851.42)]),
        )

    def fake_make_client() -> httpx.AsyncClient:
        return _make_client(handler)

    monkeypatch.setattr(indices_mod, "make_async_client", fake_make_client)

    result = asyncio.run(
        ingest(
            ["MCFTRR"],
            output_dir=tmp_path,
            cache_dir=None,
            today=date(2024, 3, 13),
        )
    )
    assert result["MCFTRR"].rows == 1
