"""Ingest MOEX index series (MCFTRR) into `data/indices/{INDEX}.csv`.

Single SECID per index, no walk-history, no board fallback. Endpoint:
`/history/engines/stock/markets/index/securities/{INDEX}.json` with `from`/`till`
window and `history.cursor` pagination — same drain shape as prices.

Idempotent: read the existing file, take `max(date)`, request `from = max + 1d`.
HTTP responses are cached to disk before parsing, so a re-run after a parse
failure does not re-hit the network.

MCFTRR is the *net* total-return index (post 13% resident tax) — matches our
backtest's `DIVIDEND_TAX`. Gross sibling MCFTR is intentionally out of scope.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx

from ingest.iss_client import cached_aget as _cached_aget
from ingest.iss_client import make_async_client
from storage.records import read_records, write_records_atomic
from storage.schemas import INDEX_CASTS, INDEX_FIELDS

LOG = logging.getLogger(__name__)

INDEX_HISTORY_PATH_TEMPLATE = "/history/engines/stock/markets/index/securities/{secid}.json"
# MCFTRR series begins 2003-02-26 on MOEX; pick a safe lower bound so the server
# clips to actual availability.
INDEX_FLOOR = date(2000, 1, 1)


@dataclass
class IndexManifest:
    first: str | None
    last: str | None
    rows: int


def _pivot_history(cols: list[str], data: list[list[Any]]) -> list[dict[str, Any]]:
    close_idx = cols.index("CLOSE")
    date_idx = cols.index("TRADEDATE")
    out: list[dict[str, Any]] = []
    for row in data:
        close = row[close_idx]
        if close is None:
            continue
        out.append({"date": str(row[date_idx]), "close": float(close)})
    return out


async def _drain_history(
    client: httpx.AsyncClient,
    secid: str,
    *,
    from_: date,
    till: date,
    cache_dir: Path | None,
    force: bool = False,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    start = 0
    url_path = INDEX_HISTORY_PATH_TEMPLATE.format(secid=secid)
    while True:
        cache_key = (
            f"indices/{secid}/from_{from_.isoformat()}_till_{till.isoformat()}_start_{start:05d}"
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


def _max_existing_date(records: list[dict[str, Any]]) -> date | None:
    if not records:
        return None
    return date.fromisoformat(max(r["date"] for r in records))


def _refetched_manifest(
    out_path: Path,
    secid: str,
    existing: list[dict[str, Any]],
    fetched: list[dict[str, Any]],
    *,
    window: tuple[date, date],
    allow_missing: bool,
) -> IndexManifest:
    """Splice a refetched window over the stored rows unless a day vanished."""
    lo, hi = window[0].isoformat(), window[1].isoformat()
    in_window = [r for r in existing if lo <= r["date"] <= hi]
    vanished = sorted({r["date"] for r in in_window} - {r["date"] for r in fetched})
    if vanished and not allow_missing:
        LOG.error("%s: refetch refused — %d date(s) vanished", secid, len(vanished))
        rows = existing
    else:
        kept = [r for r in existing if r not in in_window]
        rows = sorted(kept + fetched, key=lambda r: r["date"])
        if fetched:
            write_records_atomic(out_path, rows, fieldnames=INDEX_FIELDS)
    return IndexManifest(
        first=rows[0]["date"] if rows else None,
        last=rows[-1]["date"] if rows else None,
        rows=len(rows),
    )


async def ingest_one(
    client: httpx.AsyncClient,
    secid: str,
    *,
    output_dir: Path,
    cache_dir: Path | None,
    today: date,
    since: date | None = None,
    force: bool = False,
    refetch_from: date | None = None,
    refetch_till: date | None = None,
    allow_missing: bool = False,
) -> IndexManifest:
    """Ingest one index series. Append-only, idempotent."""
    out_path = output_dir / f"{secid}.csv"
    existing = read_records(out_path, casts=INDEX_CASTS)

    max_existing = _max_existing_date(existing)
    if max_existing is not None:
        from_ = max_existing + timedelta(days=1)
    else:
        from_ = INDEX_FLOOR
    if refetch_from is not None:
        from_ = refetch_from
    elif since is not None and since > from_:
        if max_existing is not None:
            raise ValueError(
                f"{secid}: --since {since} starts after the stored history ends "
                f"({max_existing}) and would leave a gap; use --refetch-from instead"
            )
        from_ = since
    if from_ > today:
        return IndexManifest(
            first=existing[0]["date"] if existing else None,
            last=existing[-1]["date"] if existing else None,
            rows=len(existing),
        )

    till = min(refetch_till, today) if refetch_till else today
    new_rows = await _drain_history(
        client, secid, from_=from_, till=till, cache_dir=cache_dir, force=force
    )

    if refetch_from is not None:
        return _refetched_manifest(
            out_path, secid, existing, new_rows, window=(from_, till), allow_missing=allow_missing
        )
    if existing and new_rows:
        existing_dates = {r["date"] for r in existing}
        for r in new_rows:
            if r["date"] in existing_dates:
                raise ValueError(
                    f"{secid}: unexpected overlap on {r['date']} "
                    f"(existing rows up to {max_existing})"
                )
    all_records = sorted(existing + new_rows, key=lambda r: r["date"])
    if new_rows:
        write_records_atomic(out_path, all_records, fieldnames=INDEX_FIELDS)

    return IndexManifest(
        first=all_records[0]["date"] if all_records else None,
        last=all_records[-1]["date"] if all_records else None,
        rows=len(all_records),
    )


async def ingest(
    secids: list[str],
    *,
    output_dir: Path,
    cache_dir: Path | None,
    since: date | None = None,
    today: date | None = None,
    force: bool = False,
    refetch_from: date | None = None,
    refetch_till: date | None = None,
    allow_missing: bool = False,
) -> dict[str, IndexManifest]:
    today = today or date.today()
    output_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, IndexManifest] = {}
    async with make_async_client() as client:
        for secid in secids:
            m = await ingest_one(
                client,
                secid,
                output_dir=output_dir,
                cache_dir=cache_dir,
                today=today,
                since=since,
                force=force,
                refetch_from=refetch_from,
                refetch_till=refetch_till,
                allow_missing=allow_missing,
            )
            LOG.info("%s: %d rows (first=%s last=%s)", secid, m.rows, m.first, m.last)
            results[secid] = m
    return results
