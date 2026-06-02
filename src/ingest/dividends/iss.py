"""Async ingest of dividends from MOEX ISS into `data/dividends/{TICKER}.jsonl`.

Endpoint: `/securities/{TICKER}/dividends.json?iss.meta=off`. Single-page payload
in practice (SBER full history = 6 records); we still drain `dividends.cursor` if
ISS adds one later — same defensive pattern as prices.

Record schema (only what ISS gives):
    {"registry_close": "YYYY-MM-DD", "amount": 33.30, "currency": "RUB",
     "source": "moex_iss"}

ISS has a hard depth cutoff ~2013-2014 — pre-2014 records come from other
fetchers (dohod / yahoo / tbank); see task 012.

Idempotency: dedup key is `(registry_close, amount, currency)`. A repeat run
appends nothing if ISS hasn't changed.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, cast

import httpx

from config import ISS_BASE_URL, ISS_HTTP_TIMEOUT_SECONDS, ISS_MAX_CONCURRENCY
from ingest.dividends.types import DedupKey, dedup_key
from storage.records import read_records, write_records_atomic
from storage.schemas import DIV_CASTS, DIV_FIELDS
from tickers import TickersDict

LOG = logging.getLogger(__name__)

DIVIDENDS_PATH_TEMPLATE = "/securities/{secid}/dividends.json"


@dataclass
class DividendsManifest:
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
    force: bool = False,
) -> dict[str, Any] | None:
    if cache_dir is not None and not force:
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


def _normalise_currency(code: str) -> str:
    # SUR is the legacy MOEX code for the rouble (pre-2010 records).
    return "RUB" if code.upper() == "SUR" else code.upper()


def _pivot_dividends(cols: list[str], data: list[list[Any]]) -> list[dict[str, Any]]:
    """Pivot ISS dividends payload. Drops rows with null/zero value."""
    date_idx = cols.index("registryclosedate")
    val_idx = cols.index("value")
    cur_idx = cols.index("currencyid")
    out: list[dict[str, Any]] = []
    for row in data:
        d = row[date_idx]
        v = row[val_idx]
        if d is None or v is None:
            continue
        amount = float(v)
        if amount == 0.0:
            continue
        out.append(
            {
                "registry_close": str(d),
                "amount": amount,
                "currency": _normalise_currency(str(row[cur_idx])),
                "source": "moex_iss",
            }
        )
    return out


async def _fetch_dividends(
    client: httpx.AsyncClient,
    secid: str,
    *,
    cache_dir: Path | None,
    force: bool = False,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    start = 0
    url_path = DIVIDENDS_PATH_TEMPLATE.format(secid=secid)
    while True:
        cache_key = f"dividends/{secid}/start_{start:05d}"
        payload = await _cached_aget(
            client,
            url_path,
            params={"start": str(start)},
            cache_dir=cache_dir,
            cache_key=cache_key,
            force=force,
        )
        if payload is None:
            break
        block = payload.get("dividends")
        if not block:
            break
        page_rows = block["data"]
        if not page_rows:
            break
        rows.extend(_pivot_dividends(block["columns"], page_rows))
        cursor_block = payload.get("dividends.cursor")
        if not cursor_block or not cursor_block["data"]:
            break
        idx, total, _ = cursor_block["data"][0]
        if idx + len(page_rows) >= total:
            break
        start += len(page_rows)
    return rows


def _merge(existing: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Union by (registry_close, amount, currency). Existing wins on tie."""
    by_key: dict[DedupKey, dict[str, Any]] = {dedup_key(r): r for r in existing}
    for r in new:
        by_key.setdefault(dedup_key(r), r)
    return sorted(by_key.values(), key=lambda r: (r["registry_close"], r["amount"]))


async def ingest_one(
    client: httpx.AsyncClient,
    ticker: str,
    *,
    output_dir: Path,
    cache_dir: Path | None,
    since: date | None = None,
    force: bool = False,
) -> DividendsManifest:
    """Ingest dividends for one ticker. Idempotent.

    `since` keeps the merge to ISS rows with registry_close >= it. The endpoint
    returns full history with near-dup rows curation drops; without the bound a
    re-run keeps re-introducing them into the curated file.
    """
    out_path = output_dir / f"{ticker}.csv"
    existing = read_records(out_path, casts=DIV_CASTS)
    fetched = await _fetch_dividends(client, ticker, cache_dir=cache_dir, force=force)
    if since is not None:
        cutoff = since.isoformat()
        fetched = [r for r in fetched if r["registry_close"] >= cutoff]
    merged = _merge(existing, fetched)
    if merged != existing:
        if merged:
            write_records_atomic(out_path, merged, fieldnames=DIV_FIELDS)
        # If existing was non-empty and merged is empty we keep the file as-is —
        # ISS regression should not blow away a manually-extended record.
    return DividendsManifest(
        first=merged[0]["registry_close"] if merged else None,
        last=merged[-1]["registry_close"] if merged else None,
        rows=len(merged),
    )


async def ingest(
    tickers_dict: TickersDict,
    *,
    output_dir: Path,
    cache_dir: Path | None,
    ticker_filter: list[str] | None = None,
    since: date | None = None,
    force: bool = False,
    max_concurrency: int = ISS_MAX_CONCURRENCY,
) -> dict[str, DividendsManifest]:
    selected = sorted(ticker_filter) if ticker_filter else sorted(tickers_dict.keys())
    output_dir.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(max_concurrency)
    results: dict[str, DividendsManifest] = {}

    async with make_async_client() as client:

        async def _task(t: str) -> tuple[str, DividendsManifest]:
            async with semaphore:
                m = await ingest_one(
                    client,
                    t,
                    output_dir=output_dir,
                    cache_dir=cache_dir,
                    since=since,
                    force=force,
                )
            LOG.info("%s: %d div rows (first=%s last=%s)", t, m.rows, m.first, m.last)
            return t, m

        for t, m in await asyncio.gather(*[_task(t) for t in selected]):
            results[t] = m
    return results
