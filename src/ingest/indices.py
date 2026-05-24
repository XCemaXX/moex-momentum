"""Ingest MOEX index series (MCFTRR) into `data/indices/{INDEX}.jsonl`.

Single SECID per index, no walk-history, no board fallback. Endpoint:
`/history/engines/stock/markets/index/securities/{INDEX}.json` with `from`/`till`
window and `history.cursor` pagination — same drain shape as prices.

Idempotent: read existing JSONL, take `max(date)`, request `from = max + 1d`.
HTTP responses are cached to disk before parsing, so a re-run after a parse
failure does not re-hit the network.

MCFTRR is the *net* total-return index (post 13% resident tax) — matches our
backtest's `DIVIDEND_TAX`. Gross sibling MCFTR is intentionally out of scope.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast

import httpx

from config import ISS_BASE_URL, ISS_HTTP_TIMEOUT_SECONDS
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


async def ingest_one(
    client: httpx.AsyncClient,
    secid: str,
    *,
    output_dir: Path,
    cache_dir: Path | None,
    today: date,
    since: date | None = None,
) -> IndexManifest:
    """Ingest one index series. Append-only, idempotent."""
    out_path = output_dir / f"{secid}.csv"
    existing = read_records(out_path, casts=INDEX_CASTS)

    max_existing = _max_existing_date(existing)
    if max_existing is not None:
        from_ = max_existing + timedelta(days=1)
    else:
        from_ = INDEX_FLOOR
    if since is not None and since > from_:
        from_ = since
    if from_ > today:
        return IndexManifest(
            first=existing[0]["date"] if existing else None,
            last=existing[-1]["date"] if existing else None,
            rows=len(existing),
        )

    new_rows = await _drain_history(client, secid, from_=from_, till=today, cache_dir=cache_dir)

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
            )
            LOG.info("%s: %d rows (first=%s last=%s)", secid, m.rows, m.first, m.last)
            results[secid] = m
    return results
