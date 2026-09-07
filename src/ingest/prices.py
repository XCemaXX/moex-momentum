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
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast

import httpx

from config import ISS_MAX_CONCURRENCY, ODD_LOT_BOARDS
from ingest.iss_client import cached_aget as _cached_aget
from ingest.iss_client import make_async_client
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
class RefetchReport:
    """What a refetch would do to the rows it replaces."""

    added: int = 0
    changed: int = 0
    missing: list[str] = field(default_factory=list)
    board_changed: list[str] = field(default_factory=list)
    # Suspicious rows are reported either way; this says whether they blocked the
    # write, which the allow-flags decide.
    refused: bool = False


@dataclass
class TickerManifest:
    first: str | None
    last: str | None
    rows: int
    fallback_boards: list[str]
    segments_empty: list[str]  # for audit: segments where no data was found
    refetch: RefetchReport | None = None


def _num(value: Any, to: Callable[[Any], Any]) -> Any:
    """None-preserving cast — an absent ISS field must stay empty in the CSV."""
    return None if value is None else to(value)


def _pivot_history(cols: list[str], data: list[list[Any]]) -> list[dict[str, Any]]:
    """Pivot ISS response into our JSONL format. Rows without CLOSE are dropped.

    Numeric fields are cast to match `PRICE_CASTS`: ISS returns a whole number as
    JSON int, so an uncast row would serialize as `60` and flip to `60.0` on the
    next read-back — rewriting settled history on every ingest.
    """
    out: list[dict[str, Any]] = []
    for row in data:
        rec = dict(zip(cols, row, strict=True))
        close = rec.get("CLOSE")
        if close is None:
            continue
        out.append(
            {
                "date": str(rec["TRADEDATE"]),
                "open": _num(rec.get("OPEN"), float),
                "high": _num(rec.get("HIGH"), float),
                "low": _num(rec.get("LOW"), float),
                "close": float(close),
                "volume": _num(rec.get("VOLUME"), int),
                "value": _num(rec.get("VALUE"), float),
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
    force: bool = False,
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
            force=force,
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
    """Board dicts ordered: primary, then real boards, then odd-lot, each by `history_from`.

    Among non-primary boards `history_from` alone is an arbitrary key, and odd-lot
    boards usually start earlier — so before TQBR existed they won the date and put
    a few-share print into the series. Ranking them last leaves them as the source
    only for days nothing else traded.
    """
    boards = entry.get("boards", [])
    sorted_boards = sorted(
        boards,
        key=lambda b: (
            not b.get("is_primary", False),
            b.get("board", "") in ODD_LOT_BOARDS,
            b.get("history_from", ""),
        ),
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


def _clip_segments(
    segments: list[Segment], from_filter: date, till_filter: date | None = None
) -> list[Segment]:
    """Drops segments outside the window and clips the boundary ones."""
    out: list[Segment] = []
    for s in segments:
        if s.till < from_filter:
            continue
        if till_filter is not None and s.from_ > till_filter:
            continue
        lo = max(s.from_, from_filter)
        hi = min(s.till, till_filter) if till_filter is not None else s.till
        out.append(Segment(s.secid, lo, hi) if (lo, hi) != (s.from_, s.till) else s)
    return out


def _segment_boards(
    secid: str, fallback: list[Board], tickers_dict: TickersDict | None
) -> list[Board]:
    """Boards to query for a predecessor segment: its own, then the successor's.

    The union matters both ways — the predecessor knows venues the successor has
    dropped, and an unknown SECID has no entry at all.
    """
    own = (tickers_dict or {}).get(secid)
    if not own:
        return fallback
    out = _boards_in_priority_order(own)
    seen = {b["board"] for b in out}
    out.extend(b for b in fallback if b["board"] not in seen)
    return out


async def _fetch_segment(
    client: httpx.AsyncClient,
    segment: Segment,
    boards: list[Board],
    *,
    cache_dir: Path | None,
    current_ticker: str,
    tickers_dict: TickersDict | None = None,
    force: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Query every applicable board (intersecting the segment window) in priority
    order. Union rows by date with priority dedup (primary wins on overlap).
    Returns (rows, contributing_boards).

    The board-window filter uses history_from/till from the CURRENT ticker's
    entry, so it is skipped for predecessor segments — they traded the same
    venues in earlier windows. Their board *list* comes from their own dictionary
    entry, because a venue can retire with the SECID: EONR traded EQNL, which its
    successor UPRO no longer lists, so querying UPRO's boards found nothing.
    """
    is_predecessor = segment.secid != current_ticker
    if is_predecessor:
        boards = _segment_boards(segment.secid, boards, tickers_dict)
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
            force=force,
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


def _pick_epoch(
    pred: list[dict[str, Any]], succ: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], str]:
    """Choose between a retired SECID and the live one over the same window.

    MOEX retires a SECID both when a ticker is renamed and when an additional
    issue is consolidated into the main line, and `changeover.json` does not
    distinguish them. Trading days do: an additional issue is a thin parallel
    listing, so the main line wins on volume of evidence — but ZHIV is the
    counter-example where the retired code really is the market, which is why
    this counts days instead of pattern-matching the SECID.

    Disjoint series are unioned: that is a rename whose old line went quiet
    before the new code started, and neither half is wrong.
    """
    if not pred:
        return succ, "successor"
    if not succ:
        return pred, "predecessor"
    pred_days = {r["date"] for r in pred}
    succ_days = {r["date"] for r in succ}
    if not (pred_days & succ_days):
        return merge_segments([pred, succ]), "union"
    return (pred, "predecessor") if len(pred_days) >= len(succ_days) else (succ, "successor")


async def _collect_segment_rows(
    client: httpx.AsyncClient,
    ticker: str,
    segments: list[Segment],
    boards: list[Board],
    cache_dir: Path | None,
    tickers_dict: TickersDict | None = None,
    force: bool = False,
) -> tuple[list[list[dict[str, Any]]], list[str], list[str]]:
    seg_rows_list: list[list[dict[str, Any]]] = []
    fallback_boards: set[str] = set()
    empty_segments: list[str] = []
    for seg in segments:
        rows, used = await _fetch_segment(
            client,
            seg,
            boards,
            cache_dir=cache_dir,
            current_ticker=ticker,
            tickers_dict=tickers_dict,
            force=force,
        )
        if seg.secid != ticker:
            live_rows, live_used = await _fetch_segment(
                client,
                Segment(ticker, seg.from_, seg.till),
                boards,
                cache_dir=cache_dir,
                current_ticker=ticker,
                tickers_dict=tickers_dict,
                force=force,
            )
            rows, winner = _pick_epoch(rows, live_rows)
            if winner != "predecessor":
                LOG.info(
                    "%s: segment %s %s..%s resolved to the %s line",
                    ticker,
                    seg.secid,
                    seg.from_,
                    seg.till,
                    winner,
                )
                used = sorted(set(used) | set(live_used)) if winner == "union" else live_used
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


def _refetch_report(dropped: list[dict[str, Any]], fetched: list[dict[str, Any]]) -> RefetchReport:
    """Compare the rows a refetch replaces against what came back.

    A vanished date or a date that now resolves to a different board is refused,
    not applied: board priority means the same day can legitimately carry a
    different close depending on which boards ISS still lists for the ticker.
    Changed numbers on the same board are the point of the exercise and pass.
    """
    old = {r["date"]: r for r in dropped}
    new = {r["date"]: r for r in fetched}
    rep = RefetchReport(added=len(set(new) - set(old)))
    for d in sorted(set(old) & set(new)):
        if old[d].get("board") != new[d].get("board"):
            rep.board_changed.append(d)
        elif any(old[d].get(f) != new[d].get(f) for f in PRICE_FIELDS):
            rep.changed += 1
    rep.missing = sorted(set(old) - set(new))
    return rep


def _window_floor(
    ticker: str,
    default: date,
    max_existing: date | None,
    since: date | None,
    refetch_from: date | None,
) -> date:
    """Lower bound of the fetch window.

    `--since` may only skip forward over an empty file: on a populated one it
    would write a hole between the stored tail and the requested start, and
    nothing downstream checks continuity. Reaching back is `--refetch-from`.
    """
    if refetch_from is not None:
        return refetch_from
    if since is not None and since > default:
        if max_existing is not None:
            raise ValueError(
                f"{ticker}: --since {since} starts after the stored history ends "
                f"({max_existing}) and would leave a gap; use --refetch-from instead"
            )
        return since
    return default


def _refetched_manifest(
    out_path: Path,
    ticker: str,
    existing: list[dict[str, Any]],
    fetched: list[dict[str, Any]],
    *,
    window: tuple[date, date | None],
    allow_missing: bool,
    allow_board_change: bool,
    fallback_boards: list[str],
    empty_segments: list[str],
) -> TickerManifest:
    """Splice a refetched window over the stored rows, unless the guard refuses."""
    lo, till = window
    hi = till.isoformat() if till else None
    since = lo.isoformat()
    in_window = [r for r in existing if since <= r["date"] and (hi is None or r["date"] <= hi)]
    report = _refetch_report(in_window, fetched)

    if (report.missing and not allow_missing) or (report.board_changed and not allow_board_change):
        report.refused = True
        LOG.error(
            "%s: refetch refused — %d date(s) vanished, %d changed board",
            ticker,
            len(report.missing),
            len(report.board_changed),
        )
        rows = existing
    else:
        kept = [r for r in existing if r not in in_window]
        rows = sorted(kept + fetched, key=lambda r: r["date"])
        if fetched:
            write_records_atomic(out_path, rows, fieldnames=PRICE_FIELDS)

    return TickerManifest(
        first=rows[0]["date"] if rows else None,
        last=rows[-1]["date"] if rows else None,
        rows=len(rows),
        fallback_boards=fallback_boards,
        segments_empty=empty_segments,
        refetch=report,
    )


async def ingest_one(
    client: httpx.AsyncClient,
    ticker: str,
    entry: TickerEntry,
    *,
    output_dir: Path,
    cache_dir: Path | None,
    today: date,
    since: date | None = None,
    force: bool = False,
    tickers_dict: TickersDict | None = None,
    refetch_from: date | None = None,
    refetch_till: date | None = None,
    allow_missing: bool = False,
    allow_board_change: bool = False,
) -> TickerManifest:
    """Ingest one ticker. Append-only by default; `refetch_from` replaces a window."""
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
    from_filter = _window_floor(ticker, from_filter, max_existing, since, refetch_from)
    if from_filter > end:
        return TickerManifest(
            first=existing[0]["date"] if existing else None,
            last=existing[-1]["date"] if existing else None,
            rows=len(existing),
            fallback_boards=[],
            segments_empty=[],
        )

    segments = _clip_segments(raw_segments, from_filter, refetch_till)
    boards_to_try = _boards_in_priority_order(entry)
    seg_rows_list, fallback_boards, empty_segments = await _collect_segment_rows(
        client, ticker, segments, boards_to_try, cache_dir, tickers_dict=tickers_dict, force=force
    )
    new_records = merge_segments(seg_rows_list)
    if refetch_from is not None:
        return _refetched_manifest(
            out_path,
            ticker,
            existing,
            new_records,
            window=(refetch_from, refetch_till),
            allow_missing=allow_missing,
            allow_board_change=allow_board_change,
            fallback_boards=fallback_boards,
            empty_segments=empty_segments,
        )
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
    force: bool = False,
    refetch_from: date | None = None,
    refetch_till: date | None = None,
    allow_missing: bool = False,
    allow_board_change: bool = False,
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
                    force=force,
                    tickers_dict=tickers_dict,
                    refetch_from=refetch_from,
                    refetch_till=refetch_till,
                    allow_missing=allow_missing,
                    allow_board_change=allow_board_change,
                )
            LOG.info("%s: %d rows (first=%s last=%s)", t, m.rows, m.first, m.last)
            return t, m

        for t, m in await asyncio.gather(*[_task(t) for t in selected]):
            results[t] = m
    return results
