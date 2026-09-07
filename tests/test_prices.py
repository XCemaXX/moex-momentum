"""Tests for daily quote ingest: walk segments, merge, idempotency, board fallback."""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest

from ingest.prices import (
    Segment,
    _boards_in_priority_order,
    _pivot_history,
    ingest,
    ingest_one,
    merge_segments,
    walk_segments,
)
from storage.records import read_records, write_records_atomic
from storage.schemas import PRICE_CASTS, PRICE_FIELDS
from tickers import TickerEntry

HISTORY_COLS = [
    "BOARDID",
    "TRADEDATE",
    "SHORTNAME",
    "SECID",
    "NUMTRADES",
    "VALUE",
    "OPEN",
    "LOW",
    "HIGH",
    "LEGALCLOSEPRICE",
    "WAPRICE",
    "CLOSE",
    "VOLUME",
]


def _row(board: str, secid: str, d: str, close: float) -> list[Any]:
    return [board, d, secid, secid, 1, 1000.0, close, close, close, close, close, close, 100]


def _history_payload(rows: list[list[Any]], total: int | None = None) -> dict[str, Any]:
    return {
        "history": {"columns": HISTORY_COLS, "data": rows},
        "history.cursor": {
            "columns": ["INDEX", "TOTAL", "PAGESIZE"],
            "data": [[0, total if total is not None else len(rows), 100]],
        },
    }


# ---------- walk_segments ----------


def test_walk_segments_no_history() -> None:
    entry: TickerEntry = {
        "boards": [{"board": "TQBR", "history_from": "2013-03-25", "is_primary": True}],
    }
    segs = walk_segments(entry, "SBER", date(2026, 5, 5))
    assert segs == [Segment("SBER", date(2013, 3, 25), date(2026, 5, 5))]


def test_walk_segments_single_rebrand() -> None:
    """TCSG epoch gets sentinel lower bound — boards reflect only current_secid."""
    entry: TickerEntry = {
        "boards": [{"board": "TQBR", "history_from": "2024-11-28", "is_primary": True}],
        "history": [
            {"prev_ticker": "TCSG", "renamed": "2024-11-28", "source": "iss_changeover"},
        ],
    }
    segs = walk_segments(entry, "T", date(2026, 5, 5))
    assert segs == [
        Segment("TCSG", date(2000, 1, 1), date(2024, 11, 27)),
        Segment("T", date(2024, 11, 28), date(2026, 5, 5)),
    ]


def test_walk_segments_two_step_rebrand() -> None:
    entry: TickerEntry = {
        "boards": [{"board": "TQBR", "history_from": "2023-03-15", "is_primary": True}],
        "history": [
            {"prev_ticker": "A", "renamed": "2020-06-01", "source": "iss_changeover"},
            {"prev_ticker": "B", "renamed": "2023-03-15", "source": "iss_changeover"},
        ],
    }
    segs = walk_segments(entry, "C", date(2026, 5, 5))
    assert segs == [
        Segment("A", date(2000, 1, 1), date(2020, 5, 31)),
        Segment("B", date(2020, 6, 1), date(2023, 3, 14)),
        Segment("C", date(2023, 3, 15), date(2026, 5, 5)),
    ]


def test_walk_segments_clipped_to_delisted() -> None:
    entry: TickerEntry = {
        "boards": [
            {
                "board": "TQBR",
                "history_from": "2014-06-17",
                "history_till": "2024-10-15",
                "is_primary": True,
            }
        ],
        "delisted_after": "2024-10-15",
    }
    segs = walk_segments(entry, "POLY", date(2026, 5, 5))
    assert segs == [Segment("POLY", date(2014, 6, 17), date(2024, 10, 15))]


def test_walk_segments_empty_for_no_boards() -> None:
    assert walk_segments({}, "X", date(2026, 5, 5)) == []


# ---------- merge_segments ----------


def test_merge_segments_dedups_identical_close() -> None:
    rows1 = [{"date": "2024-01-02", "close": 100.0, "board": "TQBR"}]
    rows2 = [{"date": "2024-01-02", "close": 100.0, "board": "EQBR"}]
    out = merge_segments([rows1, rows2])
    assert len(out) == 1


def test_merge_segments_conflict_raises() -> None:
    rows1 = [{"date": "2024-01-02", "close": 100.0, "board": "TQBR"}]
    rows2 = [{"date": "2024-01-02", "close": 101.0, "board": "EQBR"}]
    with pytest.raises(ValueError, match="conflict on 2024-01-02"):
        merge_segments([rows1, rows2])


def test_merge_segments_sorted_by_date() -> None:
    rows = [
        {"date": "2024-01-03", "close": 102.0},
        {"date": "2024-01-01", "close": 100.0},
        {"date": "2024-01-02", "close": 101.0},
    ]
    out = merge_segments([rows])
    assert [r["date"] for r in out] == ["2024-01-01", "2024-01-02", "2024-01-03"]


# ---------- async fetcher ----------


def _make_async_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="https://iss.moex.com/iss",
        transport=httpx.MockTransport(handler),
        params={"iss.meta": "off"},
    )


def test_ingest_one_simple(tmp_path: Path) -> None:
    entry: TickerEntry = {
        "boards": [{"board": "TQBR", "history_from": "2024-01-01", "is_primary": True}],
    }
    rows = [
        _row("TQBR", "SBER", "2024-01-02", 100.0),
        _row("TQBR", "SBER", "2024-01-03", 101.0),
        _row("TQBR", "SBER", "2024-01-04", 102.0),
    ]
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=_history_payload(rows))

    async def run() -> None:
        async with _make_async_client(handler) as client:
            m = await ingest_one(
                client,
                "SBER",
                entry,
                output_dir=tmp_path / "prices",
                cache_dir=tmp_path / "cache",
                today=date(2024, 1, 5),
            )
            assert m.rows == 3
            assert m.first == "2024-01-02"
            assert m.last == "2024-01-04"

    asyncio.run(run())
    out = tmp_path / "prices" / "SBER.csv"
    rows = read_records(out, casts=PRICE_CASTS)
    assert len(rows) == 3
    assert rows[0]["close"] == 100.0


def test_ingest_one_idempotent(tmp_path: Path) -> None:
    entry: TickerEntry = {
        "boards": [{"board": "TQBR", "history_from": "2024-01-01", "is_primary": True}],
    }
    rows = [_row("TQBR", "SBER", "2024-01-02", 100.0)]

    def handler(req: httpx.Request) -> httpx.Response:
        # On second run: from = 2024-01-03, till = 2024-01-05 → return empty.
        if req.url.params.get("from") == "2024-01-03":
            return httpx.Response(200, json=_history_payload([]))
        return httpx.Response(200, json=_history_payload(rows))

    async def run() -> None:
        async with _make_async_client(handler) as client:
            await ingest_one(
                client,
                "SBER",
                entry,
                output_dir=tmp_path / "prices",
                cache_dir=None,
                today=date(2024, 1, 5),
            )
            await ingest_one(
                client,
                "SBER",
                entry,
                output_dir=tmp_path / "prices",
                cache_dir=None,
                today=date(2024, 1, 5),
            )

    asyncio.run(run())
    out = tmp_path / "prices" / "SBER.csv"
    assert len(read_records(out, casts=PRICE_CASTS)) == 1


def test_ingest_one_board_fallback(tmp_path: Path) -> None:
    entry: TickerEntry = {
        "boards": [
            {"board": "TQBR", "history_from": "2024-01-01", "is_primary": True},
            {"board": "EQBR", "history_from": "2024-01-01", "is_primary": False},
        ],
    }

    def handler(req: httpx.Request) -> httpx.Response:
        if "/boards/TQBR/" in req.url.path:
            return httpx.Response(200, json=_history_payload([]))
        return httpx.Response(200, json=_history_payload([_row("EQBR", "X", "2024-01-02", 50.0)]))

    async def run() -> None:
        async with _make_async_client(handler) as client:
            m = await ingest_one(
                client,
                "X",
                entry,
                output_dir=tmp_path / "prices",
                cache_dir=None,
                today=date(2024, 1, 5),
            )
            assert m.fallback_boards == ["EQBR"]
            assert m.rows == 1

    asyncio.run(run())


def test_ingest_one_union_across_boards(tmp_path: Path) -> None:
    """Primary covers a recent window; secondary covers an earlier window.
    Final file should hold the union (priority dedup on overlap)."""
    entry: TickerEntry = {
        "boards": [
            {
                "board": "TQBR",
                "history_from": "2013-03-25",
                "history_till": "2026-05-04",
                "is_primary": True,
            },
            {
                "board": "EQBR",
                "history_from": "2011-11-21",
                "history_till": "2013-08-30",
                "is_primary": False,
            },
        ],
    }
    queried: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        queried.append(path)
        if "/boards/TQBR/" in path:
            rows = [
                _row("TQBR", "S", "2013-03-25", 100.0),
                _row("TQBR", "S", "2013-08-29", 110.0),
                _row("TQBR", "S", "2024-01-02", 200.0),
            ]
        elif "/boards/EQBR/" in path:
            rows = [
                _row("EQBR", "S", "2011-12-01", 80.0),
                # Overlap day — different close (small drift); primary should win.
                _row("EQBR", "S", "2013-03-25", 100.5),
                _row("EQBR", "S", "2013-08-29", 110.5),
            ]
        else:
            rows = []
        return httpx.Response(200, json=_history_payload(rows))

    async def run() -> None:
        async with _make_async_client(handler) as client:
            m = await ingest_one(
                client,
                "S",
                entry,
                output_dir=tmp_path / "prices",
                cache_dir=None,
                today=date(2024, 1, 5),
            )
            assert m.rows == 4
            assert m.first == "2011-12-01"
            assert m.last == "2024-01-02"
            assert m.fallback_boards == ["EQBR"]

    asyncio.run(run())
    out = tmp_path / "prices" / "S.csv"
    records = read_records(out, casts=PRICE_CASTS)
    by_date: dict[str, dict[str, Any]] = {r["date"]: r for r in records}
    assert by_date["2011-12-01"]["close"] == 80.0
    # Overlap date kept the primary (TQBR) close, not EQBR's 100.5.
    assert by_date["2013-03-25"]["close"] == 100.0
    assert by_date["2013-03-25"]["board"] == "TQBR"


def test_ingest_one_skips_boards_outside_segment_window(tmp_path: Path) -> None:
    """Boards whose [history_from..history_till] sit entirely outside the segment
    window must NOT be queried. Setup: existing JSONL pushes segment.from_ past
    EQBR's history_till, so EQBR should be skipped on the incremental run."""
    entry: TickerEntry = {
        "boards": [
            {
                "board": "TQBR",
                "history_from": "2013-03-25",
                "history_till": "2026-05-04",
                "is_primary": True,
            },
            {
                "board": "EQBR",
                "history_from": "2011-11-21",
                "history_till": "2013-08-30",
                "is_primary": False,
            },
        ],
    }
    # Seed existing data through 2020 so the new segment starts 2020-01-02 —
    # comfortably past EQBR's history_till (2013-08-30).
    out_dir = tmp_path / "prices"
    out_dir.mkdir(parents=True)
    write_records_atomic(
        out_dir / "X.csv",
        [{"date": "2020-01-01", "close": 50.0, "board": "TQBR"}],
        fieldnames=PRICE_FIELDS,
    )

    seen_boards: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if "/boards/TQBR/" in req.url.path:
            seen_boards.append("TQBR")
        elif "/boards/EQBR/" in req.url.path:
            seen_boards.append("EQBR")
        return httpx.Response(200, json=_history_payload([_row("TQBR", "X", "2024-01-02", 1.0)]))

    async def run() -> None:
        async with _make_async_client(handler) as client:
            await ingest_one(
                client,
                "X",
                entry,
                output_dir=out_dir,
                cache_dir=None,
                today=date(2024, 1, 5),
            )

    asyncio.run(run())
    assert "TQBR" in seen_boards
    assert "EQBR" not in seen_boards


def test_ingest_one_predecessor_skips_board_window_filter(tmp_path: Path) -> None:
    """Predecessor SECID segments traded on the same boards in earlier windows.
    The window filter uses current-secid's history_from/till — for predecessor
    segments it must be skipped, else we lose pre-rename history."""
    entry: TickerEntry = {
        "boards": [
            {
                "board": "TQBR",
                "history_from": "2013-07-08",
                "history_till": "2026-05-04",
                "is_primary": True,
            },
            # Current TATN started trading on EQBR on 2011-11-21. But predecessor
            # RU14TATN3006 traded on EQBR from 2002 to 2011 — should still be
            # queried for the predecessor segment.
            {
                "board": "EQBR",
                "history_from": "2011-11-21",
                "history_till": "2013-08-30",
                "is_primary": False,
            },
        ],
        "history": [
            {
                "prev_ticker": "RU14TATN3006",
                "renamed": "2011-11-21",
                "source": "iss_changeover",
            },
        ],
    }
    seen: list[tuple[str, str]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        secid = path.rsplit("/", 1)[-1].removesuffix(".json")
        board = path.split("/boards/")[1].split("/")[0]
        seen.append((board, secid))
        if board == "EQBR" and secid == "RU14TATN3006":
            return httpx.Response(
                200, json=_history_payload([_row("EQBR", secid, "2002-01-04", 17.9)])
            )
        if board == "TQBR" and secid == "TATN":
            return httpx.Response(
                200, json=_history_payload([_row("TQBR", "TATN", "2024-01-02", 600.0)])
            )
        return httpx.Response(200, json=_history_payload([]))

    async def run() -> None:
        async with _make_async_client(handler) as client:
            m = await ingest_one(
                client,
                "TATN",
                entry,
                output_dir=tmp_path / "prices",
                cache_dir=None,
                today=date(2024, 1, 5),
            )
            assert m.first == "2002-01-04"
            assert m.last == "2024-01-02"
            assert m.rows == 2

    asyncio.run(run())
    assert ("EQBR", "RU14TATN3006") in seen
    assert ("TQBR", "TATN") in seen


def test_ingest_one_rebrand_merges_segments(tmp_path: Path) -> None:
    entry: TickerEntry = {
        "boards": [{"board": "TQBR", "history_from": "2019-10-28", "is_primary": True}],
        "history": [
            {"prev_ticker": "TCSG", "renamed": "2024-11-28", "source": "iss_changeover"},
        ],
    }

    def handler(req: httpx.Request) -> httpx.Response:
        secid = req.url.path.rsplit("/", 1)[-1].removesuffix(".json")
        if secid == "TCSG":
            return httpx.Response(
                200, json=_history_payload([_row("TQBR", "TCSG", "2024-11-26", 3000.0)])
            )
        return httpx.Response(200, json=_history_payload([_row("TQBR", "T", "2024-11-28", 3100.0)]))

    async def run() -> None:
        async with _make_async_client(handler) as client:
            m = await ingest_one(
                client,
                "T",
                entry,
                output_dir=tmp_path / "prices",
                cache_dir=None,
                today=date(2024, 12, 1),
            )
            assert m.rows == 2
            assert m.first == "2024-11-26"
            assert m.last == "2024-11-28"

    asyncio.run(run())


def test_ingest_one_pagination(tmp_path: Path) -> None:
    entry: TickerEntry = {
        "boards": [{"board": "TQBR", "history_from": "2024-01-01", "is_primary": True}],
    }
    page1 = [_row("TQBR", "X", f"2024-01-{i:02d}", float(i)) for i in range(2, 5)]
    page2 = [_row("TQBR", "X", f"2024-01-{i:02d}", float(i)) for i in range(5, 7)]

    def handler(req: httpx.Request) -> httpx.Response:
        start = int(req.url.params.get("start", "0"))
        if start == 0:
            return httpx.Response(200, json=_history_payload(page1, total=5))
        return httpx.Response(
            200,
            json={
                "history": {"columns": HISTORY_COLS, "data": page2},
                "history.cursor": {
                    "columns": ["INDEX", "TOTAL", "PAGESIZE"],
                    "data": [[3, 5, 100]],
                },
            },
        )

    async def run() -> None:
        async with _make_async_client(handler) as client:
            m = await ingest_one(
                client,
                "X",
                entry,
                output_dir=tmp_path / "prices",
                cache_dir=None,
                today=date(2024, 1, 10),
            )
            assert m.rows == 5

    asyncio.run(run())


def test_ingest_dispatches_concurrently(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sanity: ingest() reads tickers_dict, filters by ticker_filter, writes file."""
    tickers_dict = {
        "A": {"boards": [{"board": "TQBR", "history_from": "2024-01-01", "is_primary": True}]},
        "B": {"boards": [{"board": "TQBR", "history_from": "2024-01-01", "is_primary": True}]},
    }

    def handler(req: httpx.Request) -> httpx.Response:
        secid = req.url.path.rsplit("/", 1)[-1].removesuffix(".json")
        return httpx.Response(200, json=_history_payload([_row("TQBR", secid, "2024-01-02", 1.0)]))

    def fake_make_client() -> httpx.AsyncClient:
        return _make_async_client(handler)

    monkeypatch.setattr("ingest.prices.make_async_client", fake_make_client)

    result = asyncio.run(
        ingest(
            tickers_dict,  # type: ignore[arg-type]
            output_dir=tmp_path / "prices",
            cache_dir=None,
            ticker_filter=["A"],
            today=date(2024, 1, 5),
        )
    )
    assert "A" in result and "B" not in result
    assert (tmp_path / "prices" / "A.csv").exists()
    assert not (tmp_path / "prices" / "B.csv").exists()


# ---------- _pivot_history casts ----------


def test_pivot_history_casts_match_price_casts() -> None:
    """ISS whole numbers arrive as JSON int; uncast they would flip to float on
    read-back and rewrite settled history on every ingest."""
    row = ["TQBR", "2026-07-07", "A", "A", 1, 23421021, 46, 43, 46, 45.7, 45.7, 45.7, 522120]
    rec = _pivot_history(HISTORY_COLS, [row])[0]
    for field, expected in (
        ("open", float),
        ("high", float),
        ("low", float),
        ("close", float),
        ("value", float),
        ("volume", int),
    ):
        assert type(rec[field]) is expected, f"{field}: {type(rec[field])}"


def test_pivot_history_keeps_missing_numeric_none() -> None:
    row = ["TQBR", "2026-07-07", "A", "A", 1, None, None, None, None, 45.7, 45.7, 45.7, None]
    rec = _pivot_history(HISTORY_COLS, [row])[0]
    assert rec["open"] is None and rec["value"] is None and rec["volume"] is None


def test_force_refresh_bypasses_the_cache(tmp_path: Path) -> None:
    """A force flag that silently does nothing cost four months once — see task 029."""
    cache = tmp_path / "cache"
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(
            200, json=_history_payload([_row("TQBR", "SBER", "2024-03-13", 298.85)])
        )

    entry: Any = {
        "boards": [{"board": "TQBR", "is_primary": 1, "history_from": "2024-03-01"}],
        "history_from": "2024-03-01",
    }

    async def run(out: Path, *, force: bool) -> None:
        async with _make_async_client(handler) as client:
            await ingest_one(
                client,
                "SBER",
                entry,
                output_dir=out,
                cache_dir=cache,
                today=date(2024, 3, 13),
                force=force,
            )

    asyncio.run(run(tmp_path / "a", force=False))
    first = len(calls)
    assert first >= 1
    asyncio.run(run(tmp_path / "b", force=False))
    assert len(calls) == first, "a plain re-run must read the cache"
    asyncio.run(run(tmp_path / "c", force=True))
    assert len(calls) == 2 * first, "--force-refresh must re-fetch"


def _seed_prices(path: Path, rows: list[tuple[str, float, str]]) -> None:
    write_records_atomic(
        path,
        [
            {
                "date": d,
                "open": c,
                "high": c,
                "low": c,
                "close": c,
                "volume": 100,
                "value": 1000.0,
                "board": b,
            }
            for d, c, b in rows
        ],
        fieldnames=PRICE_FIELDS,
    )


def _refetch_entry() -> Any:
    return {
        "boards": [{"board": "TQBR", "is_primary": 1, "history_from": "2024-01-01"}],
        "history_from": "2024-01-01",
    }


async def _run_refetch(out: Path, handler: Any, **kw: Any) -> Any:
    async with _make_async_client(handler) as client:
        return await ingest_one(
            client,
            "SBER",
            _refetch_entry(),
            output_dir=out,
            cache_dir=None,
            today=date(2024, 3, 5),
            **kw,
        )


def test_refetch_of_an_unchanged_window_keeps_the_file(tmp_path: Path) -> None:
    out = tmp_path / "d"
    _seed_prices(out / "SBER.csv", [("2024-03-01", 100.0, "TQBR"), ("2024-03-04", 101.0, "TQBR")])
    before = (out / "SBER.csv").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_history_payload(
                [
                    _row("TQBR", "SBER", "2024-03-01", 100.0),
                    _row("TQBR", "SBER", "2024-03-04", 101.0),
                ]
            ),
        )

    m = asyncio.run(_run_refetch(out, handler, refetch_from=date(2024, 3, 1)))
    assert (out / "SBER.csv").read_bytes() == before
    assert m.refetch is not None and m.refetch.changed == 0 and m.refetch.added == 0


def test_refetch_applies_a_changed_close(tmp_path: Path) -> None:
    out = tmp_path / "d"
    _seed_prices(out / "SBER.csv", [("2024-03-01", 100.0, "TQBR"), ("2024-03-04", 101.0, "TQBR")])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_history_payload(
                [
                    _row("TQBR", "SBER", "2024-03-01", 100.0),
                    _row("TQBR", "SBER", "2024-03-04", 999.0),
                ]
            ),
        )

    m = asyncio.run(_run_refetch(out, handler, refetch_from=date(2024, 3, 1)))
    rows = read_records(out / "SBER.csv", casts=PRICE_CASTS)
    assert [r["close"] for r in rows] == [100.0, 999.0]
    assert m.refetch is not None and m.refetch.changed == 1


def test_refetch_refuses_when_a_day_vanished(tmp_path: Path) -> None:
    out = tmp_path / "d"
    _seed_prices(out / "SBER.csv", [("2024-03-01", 100.0, "TQBR"), ("2024-03-04", 101.0, "TQBR")])
    before = (out / "SBER.csv").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=_history_payload([_row("TQBR", "SBER", "2024-03-01", 100.0)])
        )

    m = asyncio.run(_run_refetch(out, handler, refetch_from=date(2024, 3, 1)))
    assert (out / "SBER.csv").read_bytes() == before, "a refused refetch must not write"
    assert m.refetch is not None and m.refetch.missing == ["2024-03-04"] and m.refetch.refused

    m2 = asyncio.run(_run_refetch(out, handler, refetch_from=date(2024, 3, 1), allow_missing=True))
    assert m2.rows == 1


def test_refetch_refuses_when_the_board_changed(tmp_path: Path) -> None:
    """Board priority means the same day can carry a different close per board."""
    out = tmp_path / "d"
    _seed_prices(out / "SBER.csv", [("2024-03-01", 100.0, "SMAL")])
    before = (out / "SBER.csv").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=_history_payload([_row("TQBR", "SBER", "2024-03-01", 100.0)])
        )

    m = asyncio.run(_run_refetch(out, handler, refetch_from=date(2024, 3, 1)))
    assert (out / "SBER.csv").read_bytes() == before
    assert m.refetch is not None and m.refetch.board_changed == ["2024-03-01"]
    assert m.refetch.refused

    m2 = asyncio.run(
        _run_refetch(out, handler, refetch_from=date(2024, 3, 1), allow_board_change=True)
    )
    assert m2.refetch is not None and not m2.refetch.refused, (
        "an accepted board change must not report as refused"
    )
    assert read_records(out / "SBER.csv", casts=PRICE_CASTS)[0]["board"] == "TQBR"


def test_refetch_till_keeps_the_tail(tmp_path: Path) -> None:
    out = tmp_path / "d"
    _seed_prices(
        out / "SBER.csv",
        [
            ("2024-03-01", 100.0, "TQBR"),
            ("2024-03-04", 101.0, "TQBR"),
            ("2024-03-05", 102.0, "TQBR"),
        ],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=_history_payload([_row("TQBR", "SBER", "2024-03-01", 555.0)])
        )

    asyncio.run(
        _run_refetch(out, handler, refetch_from=date(2024, 3, 1), refetch_till=date(2024, 3, 1))
    )
    rows = read_records(out / "SBER.csv", casts=PRICE_CASTS)
    assert [r["close"] for r in rows] == [555.0, 101.0, 102.0]


def test_refetch_writes_nothing_when_the_fetch_is_empty(tmp_path: Path) -> None:
    out = tmp_path / "d"
    _seed_prices(out / "SBER.csv", [("2024-03-01", 100.0, "TQBR")])
    before = (out / "SBER.csv").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_history_payload([]))

    asyncio.run(_run_refetch(out, handler, refetch_from=date(2024, 3, 1), allow_missing=True))
    assert (out / "SBER.csv").read_bytes() == before


def test_since_past_the_stored_tail_is_refused(tmp_path: Path) -> None:
    """It used to write a hole between the stored tail and the requested start."""
    out = tmp_path / "d"
    _seed_prices(out / "SBER.csv", [("2024-01-05", 100.0, "TQBR")])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_history_payload([]))

    with pytest.raises(ValueError, match="would leave a gap"):
        asyncio.run(_run_refetch(out, handler, since=date(2024, 3, 1)))


def test_odd_lot_board_ranks_below_a_later_starting_real_board() -> None:
    """Before TQBR existed, SMAL's earlier history_from used to win the date."""
    entry: Any = {
        "boards": [
            {"board": "SMAL", "is_primary": 0, "history_from": "2011-03-01"},
            {"board": "TQNE", "is_primary": 0, "history_from": "2013-03-25"},
            {"board": "TQBR", "is_primary": 1, "history_from": "2014-06-01"},
        ]
    }
    assert [b["board"] for b in _boards_in_priority_order(entry)] == ["TQBR", "TQNE", "SMAL"]


def test_odd_lot_board_still_supplies_days_nothing_else_traded(tmp_path: Path) -> None:
    """1324 ticker-months have no other board; dropping them would void eligibility."""
    entry: Any = {
        "boards": [
            {"board": "SMAL", "is_primary": 0, "history_from": "2013-01-01"},
            {"board": "TQNE", "is_primary": 0, "history_from": "2013-01-01"},
        ],
        "history_from": "2013-01-01",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        board = str(request.url).split("/boards/")[1].split("/")[0]
        rows = [_row("SMAL", "SBER", "2013-01-09", 50.0)] if board == "SMAL" else []
        return httpx.Response(200, json=_history_payload(rows))

    async def run() -> None:
        async with _make_async_client(handler) as client:
            await ingest_one(
                client,
                "SBER",
                entry,
                output_dir=tmp_path,
                cache_dir=None,
                today=date(2013, 1, 10),
            )

    asyncio.run(run())
    rows = read_records(tmp_path / "SBER.csv", casts=PRICE_CASTS)
    assert [(r["date"], r["board"]) for r in rows] == [("2013-01-09", "SMAL")]


def test_predecessor_boards_come_from_its_own_entry(tmp_path: Path) -> None:
    """EONR traded EQNL, which its successor UPRO no longer lists."""
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        asked.append(url.split("/boards/")[1].split(".json", maxsplit=1)[0])
        return httpx.Response(200, json=_history_payload([]))

    entry: Any = {
        "boards": [{"board": "TQBR", "is_primary": 1, "history_from": "2016-07-01"}],
        "history": [{"renamed": "2016-07-01", "prev_ticker": "EONR"}],
        "history_from": "2016-07-01",
    }
    dictionary: Any = {
        "UPRO": entry,
        "EONR": {"boards": [{"board": "EQNL", "is_primary": 0, "history_from": "2008-01-01"}]},
    }

    async def run() -> None:
        async with _make_async_client(handler) as client:
            await ingest_one(
                client,
                "UPRO",
                entry,
                output_dir=tmp_path,
                cache_dir=None,
                today=date(2016, 8, 1),
                tickers_dict=dictionary,
            )

    asyncio.run(run())
    assert any("EQNL/securities/EONR" in a for a in asked), (
        "the predecessor's own board must be queried"
    )


def _epoch_row(secid: str, d: str) -> list[Any]:
    return _row("TQBR", secid, d, 100.0)


def test_thin_additional_issue_loses_to_the_main_line(tmp_path: Path) -> None:
    """`changeover.json` retires a SECID for a rename and for a consolidated issue alike."""
    entry: Any = {
        "boards": [{"board": "TQBR", "is_primary": 1, "history_from": "2013-01-01"}],
        "history": [{"renamed": "2014-07-14", "prev_ticker": "HYDR-041D"}],
        "history_from": "2013-01-01",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        secid = str(request.url).split("/securities/")[1].split(".json")[0]
        days = ["2014-03-03", "2014-03-04", "2014-03-05"] if secid == "HYDR" else ["2014-03-03"]
        return httpx.Response(200, json=_history_payload([_epoch_row(secid, d) for d in days]))

    async def run() -> None:
        async with _make_async_client(handler) as client:
            await ingest_one(
                client,
                "HYDR",
                entry,
                output_dir=tmp_path,
                cache_dir=None,
                today=date(2014, 3, 5),
                tickers_dict={"HYDR": entry},
            )

    asyncio.run(run())
    assert len(read_records(tmp_path / "HYDR.csv", casts=PRICE_CASTS)) == 3


def test_retired_secid_wins_when_it_is_the_market(tmp_path: Path) -> None:
    """ZHIV: the retired line traded 88 days, the main line 2 — no regex would know."""
    entry: Any = {
        "boards": [{"board": "TQBR", "is_primary": 1, "history_from": "2013-01-01"}],
        "history": [{"renamed": "2013-11-25", "prev_ticker": "ZHIV-001D"}],
        "history_from": "2013-01-01",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        secid = str(request.url).split("/securities/")[1].split(".json")[0]
        days = (
            ["2013-06-03", "2013-06-04", "2013-06-05"] if secid == "ZHIV-001D" else ["2013-06-03"]
        )
        return httpx.Response(200, json=_history_payload([_epoch_row(secid, d) for d in days]))

    async def run() -> None:
        async with _make_async_client(handler) as client:
            await ingest_one(
                client,
                "ZHIV",
                entry,
                output_dir=tmp_path,
                cache_dir=None,
                today=date(2013, 6, 5),
                tickers_dict={"ZHIV": entry},
            )

    asyncio.run(run())
    assert len(read_records(tmp_path / "ZHIV.csv", casts=PRICE_CASTS)) == 3


def test_disjoint_epochs_are_unioned(tmp_path: Path) -> None:
    """A rename whose old line went quiet before the new code started loses nothing."""
    entry: Any = {
        "boards": [{"board": "TQBR", "is_primary": 1, "history_from": "2013-01-01"}],
        "history": [{"renamed": "2013-06-10", "prev_ticker": "OLD"}],
        "history_from": "2013-01-01",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        secid = str(request.url).split("/securities/")[1].split(".json")[0]
        days = ["2013-06-03"] if secid == "OLD" else ["2013-06-05"]
        return httpx.Response(200, json=_history_payload([_epoch_row(secid, d) for d in days]))

    async def run() -> None:
        async with _make_async_client(handler) as client:
            await ingest_one(
                client,
                "NEW",
                entry,
                output_dir=tmp_path,
                cache_dir=None,
                today=date(2013, 6, 9),
                tickers_dict={"NEW": entry},
            )

    asyncio.run(run())
    dates = [r["date"] for r in read_records(tmp_path / "NEW.csv", casts=PRICE_CASTS)]
    assert dates == ["2013-06-03", "2013-06-05"]
