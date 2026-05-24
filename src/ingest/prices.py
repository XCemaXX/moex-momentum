"""Async ingest of daily quotes from MOEX ISS into `data/prices_iss/{TICKER}.jsonl`.

Contract:
- `ingest(tickers, *, output_dir, cache_dir, ...)` — async, ~10 parallel GETs.
- Per-ticker: walk history (multi-step changeover); for each segment try boards in
  order `(is_primary desc, history_from asc)`. First non-empty = winner.
- Append-only: on a repeat run we read the existing JSONL, take `max(date)`, and
  request `from = max_date + 1d`. Idempotent: a repeat run does not change a byte.
- Cache HTTP pages to disk *before* parsing/merging (see lesson learned phase 3).
- Price (CLOSE) conflict on a single date from different segments = `ValueError`.

Redomiciliations from `tickers_manual.json` (`type=redomicile`) are **not stitched** —
those are legally distinct securities with discontinuous history. Only `entry["history"]`
(source `iss_changeover`) is expanded into segments.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast

import httpx

from config import ISS_BASE_URL, ISS_HTTP_TIMEOUT_SECONDS, ISS_MAX_CONCURRENCY
from storage.records import read_records, write_records_atomic
from storage.schemas import PRICE_CASTS, PRICE_FIELDS
from tickers import Board, TickerEntry, TickersDict

LOG = logging.getLogger(__name__)

PRIMARY_BOARD = "TQBR"
# Sentinel lower-bound date for predecessor epochs: their own boards.history_from
# is absent in the current dictionary (boards are tied to current_secid). Pick
# something far before any MOEX ISS data — the server simply returns nothing past history.
PRIOR_EPOCH_FLOOR = date(2000, 1, 1)
HISTORY_PATH_TEMPLATE = (
    "/history/engines/stock/markets/shares/boards/{board}/securities/{secid}.json"
)


@dataclass(frozen=True)
class Segment:
    """One slice of history under a specific SECID and time window."""

    secid: str
    from_: date
    till: date


@dataclass
class TickerManifest:
    first: str | None
    last: str | None
    rows: int
    fallback_boards: list[str]
    segments_empty: list[str]  # for audit: segments where no data was found


def make_async_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=ISS_BASE_URL,
        timeout=ISS_HTTP_TIMEOUT_SECONDS,
        params={"iss.meta": "off"},
        headers={"User-Agent": "moex-momentum/0.1"},
    )


def _cache_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / f"{key}.json"


async def _cached_aget(
    client: httpx.AsyncClient,
    url_path: str,
    *,
    params: dict[str, str],
    cache_dir: Path | None,
    cache_key: str,
) -> dict[str, Any] | None:
    """Async GET with cache. Returns `None` for 404. Atomic write via `.tmp`+rename."""
    if cache_dir is not None:
        cp = _cache_path(cache_dir, cache_key)
        if cp.exists():
            with cp.open(encoding="utf-8") as f:
                return cast(dict[str, Any], json.load(f))
    resp = await client.get(url_path, params=params)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    data: Any = resp.json()
    if cache_dir is not None:
        cp = _cache_path(cache_dir, cache_key)
        cp.parent.mkdir(parents=True, exist_ok=True)
        tmp = cp.with_suffix(cp.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        tmp.replace(cp)
    return cast(dict[str, Any], data)


def _pivot_history(cols: list[str], data: list[list[Any]]) -> list[dict[str, Any]]:
    """Pivot ISS response into our JSONL format. Rows without CLOSE are dropped."""
    out: list[dict[str, Any]] = []
    for row in data:
        rec = dict(zip(cols, row, strict=True))
        close = rec.get("CLOSE")
        if close is None:
            continue
        out.append(
            {
                "date": str(rec["TRADEDATE"]),
                "open": rec.get("OPEN"),
                "high": rec.get("HIGH"),
                "low": rec.get("LOW"),
                "close": float(close),
                "volume": rec.get("VOLUME"),
                "value": rec.get("VALUE"),
                "board": str(rec["BOARDID"]),
            }
        )
    return out


async def _drain_history(
    client: httpx.AsyncClient,
    board: str,
    secid: str,
    *,
    from_: date,
    till: date,
    cache_dir: Path | None,
) -> list[dict[str, Any]]:
    """Pulls all pages of /history/.../boards/{board}/securities/{secid}.json."""
    rows: list[dict[str, Any]] = []
    start = 0
    url_path = HISTORY_PATH_TEMPLATE.format(board=board, secid=secid)
    while True:
        cache_key = (
            f"prices/{secid}/{board}/from_{from_.isoformat()}_till_{till.isoformat()}"
            f"_start_{start:05d}"
        )
        payload = await _cached_aget(
            client,
            url_path,
            params={
                "from": from_.isoformat(),
                "till": till.isoformat(),
                "start": str(start),
                "iss.only": "history,history.cursor",
            },
            cache_dir=cache_dir,
            cache_key=cache_key,
        )
        if payload is None:
            break
        block = payload["history"]
        page_rows = block["data"]
        if not page_rows:
            break
        rows.extend(_pivot_history(block["columns"], page_rows))
        cursor_block = payload.get("history.cursor")
        if not cursor_block or not cursor_block["data"]:
            break
        idx, total, _ = cursor_block["data"][0]
        if idx + len(page_rows) >= total:
            break
        start += len(page_rows)
    return rows


def _boards_in_priority_order(entry: TickerEntry) -> list[Board]:
    """Board dicts ordered: primary first, then by `history_from` asc."""
    boards = entry.get("boards", [])
    sorted_boards = sorted(
        boards,
        key=lambda b: (not b.get("is_primary", False), b.get("history_from", "")),
    )
    return [b for b in sorted_boards if "board" in b]


def _board_in_segment_window(board: Board, seg_from: date, seg_till: date) -> bool:
    """Skip boards whose [history_from..history_till] does not intersect the segment."""
    hf = board.get("history_from")
    ht = board.get("history_till")
    if hf and date.fromisoformat(hf) > seg_till:
        return False
    if ht and date.fromisoformat(ht) < seg_from:
        return False
    return True


def _merge_boards_priority(
    per_board_rows: list[tuple[str, list[dict[str, Any]]]],
) -> list[dict[str, Any]]:
    """Dedup-by-date across boards. First board in input order wins on a duplicate
    date (callers pass boards in priority order). Small CLOSE drift across boards
    on overlap days is normal (different sessions) — no conflict check here.
    Use `merge_segments` for cross-segment merges where CLOSE conflicts mean real
    data issues."""
    by_date: dict[str, dict[str, Any]] = {}
    for _, rows in per_board_rows:
        for rec in rows:
            d = rec["date"]
            if d in by_date:
                continue
            by_date[d] = rec
    return sorted(by_date.values(), key=lambda r: r["date"])


def _listing_window(entry: TickerEntry, today: date) -> tuple[date, date] | None:
    """[earliest history_from across boards .. delisted_after | today]. None if no boards."""
    boards = entry.get("boards", [])
    froms = [b.get("history_from") for b in boards if b.get("history_from")]
    if not froms:
        return None
    start = date.fromisoformat(min(cast(list[str], froms)))
    end_str = entry.get("delisted_after")
    end = date.fromisoformat(end_str) if end_str else today
    if end < start:
        return None
    return start, end


def walk_segments(entry: TickerEntry, current_secid: str, today: date) -> list[Segment]:
    """Expands entry.history into segments (oldest first).

    `boards.history_from` reflects the *current_secid* epoch — used as the start of
    the most recent segment. Predecessor epochs have no boards of their own in our
    dictionary, so we start from PRIOR_EPOCH_FLOOR (ISS will clip to available).
    """
    window = _listing_window(entry, today)
    if window is None:
        return []
    listing_start, end = window
    history = sorted(entry.get("history", []), key=lambda h: h["renamed"])
    if not history:
        return [Segment(current_secid, listing_start, end)] if listing_start <= end else []

    segments: list[Segment] = []
    last_renamed = date.fromisoformat(history[-1]["renamed"])
    current_seg_start = max(last_renamed, listing_start)
    if current_seg_start <= end:
        segments.append(Segment(current_secid, current_seg_start, end))

    cur_till = last_renamed - timedelta(days=1)
    for i in range(len(history) - 1, -1, -1):
        prev_secid = history[i]["prev_ticker"]
        seg_from = PRIOR_EPOCH_FLOOR if i == 0 else date.fromisoformat(history[i - 1]["renamed"])
        if seg_from <= cur_till:
            segments.append(Segment(prev_secid, seg_from, cur_till))
        cur_till = seg_from - timedelta(days=1)

    segments.reverse()
    return segments


def _clip_segments(segments: list[Segment], from_filter: date) -> list[Segment]:
    """Drops segments entirely in the past and clips the boundary one."""
    out: list[Segment] = []
    for s in segments:
        if s.till < from_filter:
            continue
        if s.from_ < from_filter:
            out.append(Segment(s.secid, from_filter, s.till))
        else:
            out.append(s)
    return out


async def _fetch_segment(
    client: httpx.AsyncClient,
    segment: Segment,
    boards: list[Board],
    *,
    cache_dir: Path | None,
    current_ticker: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Query every applicable board (intersecting the segment window) in priority
    order. Union rows by date with priority dedup (primary wins on overlap).
    Returns (rows, contributing_boards).

    The board-window filter uses history_from/till from the CURRENT ticker's
    entry. Predecessor SECID segments traded on the same boards in different
    (usually earlier) windows — for those, skip the filter and try every board.
    Constraint: predecessor recovery only works for boards still listed in the
    current entry — boards that vanished between SECID epochs are not queried.
    """
    is_predecessor = segment.secid != current_ticker
    per_board: list[tuple[str, list[dict[str, Any]]]] = []
    for b in boards:
        if not is_predecessor and not _board_in_segment_window(b, segment.from_, segment.till):
            continue
        rows = await _drain_history(
            client,
            b["board"],
            segment.secid,
            from_=segment.from_,
            till=segment.till,
            cache_dir=cache_dir,
        )
        if rows:
            per_board.append((b["board"], rows))
    if not per_board:
        return [], []
    merged = _merge_boards_priority(per_board)
    return merged, [b for b, _ in per_board]


def merge_segments(seg_rows_list: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Dedup by date. CLOSE conflict on a single date → fail."""
    by_date: dict[str, dict[str, Any]] = {}
    for seg in seg_rows_list:
        for rec in seg:
            d = rec["date"]
            if d in by_date:
                a = by_date[d]["close"]
                b = rec["close"]
                if abs(a - b) > 1e-6:
                    raise ValueError(
                        f"price conflict on {d}: {by_date[d]['board']}={a} vs {rec['board']}={b}"
                    )
                continue
            by_date[d] = rec
    return sorted(by_date.values(), key=lambda r: r["date"])


async def _collect_segment_rows(
    client: httpx.AsyncClient,
    ticker: str,
    segments: list[Segment],
    boards: list[Board],
    cache_dir: Path | None,
) -> tuple[list[list[dict[str, Any]]], list[str], list[str]]:
    seg_rows_list: list[list[dict[str, Any]]] = []
    fallback_boards: set[str] = set()
    empty_segments: list[str] = []
    for seg in segments:
        rows, used = await _fetch_segment(
            client, seg, boards, cache_dir=cache_dir, current_ticker=ticker
        )
        if not used:
            empty_segments.append(f"{seg.secid}:{seg.from_}..{seg.till}")
            LOG.warning(
                "%s: segment %s %s..%s — empty on all boards",
                ticker,
                seg.secid,
                seg.from_,
                seg.till,
            )
            continue
        for b in used:
            if b != PRIMARY_BOARD:
                fallback_boards.add(b)
        if used != [PRIMARY_BOARD]:
            LOG.info(
                "%s: segment %s %s..%s pulled from boards %s",
                ticker,
                seg.secid,
                seg.from_,
                seg.till,
                used,
            )
        seg_rows_list.append(rows)
    return seg_rows_list, sorted(fallback_boards), empty_segments


def _max_existing_date(records: list[dict[str, Any]]) -> date | None:
    if not records:
        return None
    return date.fromisoformat(max(r["date"] for r in records))


async def ingest_one(
    client: httpx.AsyncClient,
    ticker: str,
    entry: TickerEntry,
    *,
    output_dir: Path,
    cache_dir: Path | None,
    today: date,
    since: date | None = None,
) -> TickerManifest:
    """Ingest one ticker. Append-only, idempotent."""
    out_path = output_dir / f"{ticker}.csv"
    existing = read_records(out_path, casts=PRICE_CASTS)

    window = _listing_window(entry, today)
    if window is None:
        LOG.warning("%s: no boards with history_from, skip", ticker)
        return TickerManifest(None, None, 0, [], [])

    _, end = window
    raw_segments = walk_segments(entry, ticker, end)
    if not raw_segments:
        return TickerManifest(None, None, 0, [], [])
    earliest = raw_segments[0].from_
    max_existing = _max_existing_date(existing)
    if max_existing is not None:
        from_filter = max_existing + timedelta(days=1)
    else:
        from_filter = earliest
    if since is not None and since > from_filter:
        from_filter = since
    if from_filter > end:
        return TickerManifest(
            first=existing[0]["date"] if existing else None,
            last=existing[-1]["date"] if existing else None,
            rows=len(existing),
            fallback_boards=[],
            segments_empty=[],
        )

    segments = _clip_segments(raw_segments, from_filter)
    boards_to_try = _boards_in_priority_order(entry)
    seg_rows_list, fallback_boards, empty_segments = await _collect_segment_rows(
        client, ticker, segments, boards_to_try, cache_dir
    )
    new_records = merge_segments(seg_rows_list)
    if existing and new_records:
        existing_dates = {r["date"] for r in existing}
        for r in new_records:
            if r["date"] in existing_dates:
                raise ValueError(
                    f"{ticker}: unexpected overlap on {r['date']} "
                    f"(existing rows up to {max_existing})"
                )
        all_records = sorted(existing + new_records, key=lambda r: r["date"])
    else:
        all_records = existing + new_records

    if new_records:
        write_records_atomic(out_path, all_records, fieldnames=PRICE_FIELDS)

    return TickerManifest(
        first=all_records[0]["date"] if all_records else None,
        last=all_records[-1]["date"] if all_records else None,
        rows=len(all_records),
        fallback_boards=fallback_boards,
        segments_empty=empty_segments,
    )


async def ingest(
    tickers_dict: TickersDict,
    *,
    output_dir: Path,
    cache_dir: Path | None,
    ticker_filter: list[str] | None = None,
    since: date | None = None,
    today: date | None = None,
    max_concurrency: int = ISS_MAX_CONCURRENCY,
) -> dict[str, TickerManifest]:
    today = today or date.today()
    selected = sorted(ticker_filter) if ticker_filter else sorted(tickers_dict.keys())
    output_dir.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(max_concurrency)
    results: dict[str, TickerManifest] = {}

    async with make_async_client() as client:

        async def _task(t: str) -> tuple[str, TickerManifest]:
            entry = tickers_dict.get(t)
            if entry is None:
                LOG.warning("%s: not in tickers_dict, skip", t)
                return t, TickerManifest(None, None, 0, [], [])
            async with semaphore:
                m = await ingest_one(
                    client,
                    t,
                    entry,
                    output_dir=output_dir,
                    cache_dir=cache_dir,
                    today=today,
                    since=since,
                )
            LOG.info("%s: %d rows (first=%s last=%s)", t, m.rows, m.first, m.last)
            return t, m

        for t, m in await asyncio.gather(*[_task(t) for t in selected]):
            results[t] = m
    return results
