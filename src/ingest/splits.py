"""Ingest of share splits + bonus issues into `data/splits/{TICKER}.jsonl`.

Two sources:
- MOEX ISS `/iss/statistics/engines/stock/splits.json` — bulk endpoint, ~55 rows
  total across the exchange. One request, no pagination.
- `data/tickers_manual.json` `type=bonus_issue` entries — bonus issues are
  mathematically identical to forward splits but ISS does not publish them.

Record shape (raw before/after; back-adjustment coefficient = before/after lives
in `apply.py`):

    {"date": "2024-07-15", "before": 5000, "after": 1,
     "type": "reverse", "source": "moex_iss"}

Filters on ISS rows: drop SECIDs ending in `-RM` (foreign DRs), starting with
`FIX` (MOEX fixings, not equity), in ISIN form (`RU000A...`). Keep only entries
present in `tickers.json` with `type == "share"`.

Idempotency: dedup key is `(date, before, after)`; manual override wins on tie.
"""

from __future__ import annotations

import json
import logging
import re
from fractions import Fraction
from pathlib import Path
from typing import Any, cast

import httpx

from config import ISS_BASE_URL, ISS_HTTP_TIMEOUT_SECONDS
from storage.records import read_records, write_records_atomic
from storage.schemas import SPLIT_CASTS, SPLIT_FIELDS
from tickers import ManualEntry, TickersDict

LOG = logging.getLogger(__name__)

SPLITS_PATH = "/statistics/engines/stock/splits.json"
ISIN_RE = re.compile(r"^RU000A")


def make_client() -> httpx.Client:
    return httpx.Client(
        base_url=ISS_BASE_URL,
        timeout=ISS_HTTP_TIMEOUT_SECONDS,
        params={"iss.meta": "off"},
        headers={"User-Agent": "moex-momentum/0.1"},
    )


def _is_equity_secid(secid: str, tickers: TickersDict) -> bool:
    """Drop foreign DRs / fixings / ISIN-shaped rows; keep `type=share`."""
    if secid.endswith("-RM") or secid.startswith("FIX") or ISIN_RE.match(secid):
        return False
    entry = tickers.get(secid)
    return entry is not None and entry.get("type") == "share"


def _split_type(before: int, after: int) -> str:
    if before < after:
        return "forward"
    if before > after:
        return "reverse"
    raise ValueError(f"split with before==after ({before}) is a no-op")


def _parse_iss(payload: dict[str, Any], tickers: TickersDict) -> dict[str, list[dict[str, Any]]]:
    """ISS payload → {ticker: [record, ...]}. Filtered to equities."""
    block = payload["splits"]
    cols: list[str] = block["columns"]
    rows: list[list[Any]] = block["data"]
    date_idx = cols.index("tradedate")
    secid_idx = cols.index("secid")
    before_idx = cols.index("before")
    after_idx = cols.index("after")
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        secid = str(row[secid_idx]).upper()
        if not _is_equity_secid(secid, tickers):
            continue
        before = int(row[before_idx])
        after = int(row[after_idx])
        if before == after:
            continue
        out.setdefault(secid, []).append(
            {
                "date": str(row[date_idx]),
                "before": before,
                "after": after,
                "type": _split_type(before, after),
                "source": "moex_iss",
            }
        )
    return out


def _ratio_to_record(entry: ManualEntry) -> dict[str, Any]:
    """Convert a ratio-bearing manual entry (bonus_issue or reverse_split)
    into a split record.

    `ratio = before/after` regardless of direction:
        - BELU 1:8 bonus      → ratio=0.125 → before=1, after=8 (price ÷ 8)
        - IRAO 100:1 reverse  → ratio=100   → before=100, after=1 (price × 100)
    """
    ratio = entry.get("ratio")
    if ratio is None:
        raise ValueError(f"{entry.get('type')} {entry.get('old_secid')}: missing ratio")
    f = Fraction(ratio).limit_denominator(10000)
    rec_type = entry.get("type", "bonus_issue")
    return {
        "date": entry["renamed"],
        "before": f.numerator,
        "after": f.denominator,
        "type": rec_type,
        "source": f"manual_{rec_type}",
    }


def _parse_manual(manual: list[ManualEntry]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for e in manual:
        if e.get("type") not in ("bonus_issue", "reverse_split"):
            continue
        old = e["old_secid"]
        new = e["new_secid"]
        if old != new:
            raise ValueError(f"{e['type']} {old}→{new}: SECID must not change")
        out.setdefault(new.upper(), []).append(_ratio_to_record(e))
    return out


def _dedup_key(rec: dict[str, Any]) -> tuple[str, int, int]:
    return (rec["date"], int(rec["before"]), int(rec["after"]))


def _merge_records(
    existing: list[dict[str, Any]],
    iss_recs: list[dict[str, Any]],
    manual_recs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Manual override wins on equal (date, before, after); existing wins otherwise."""
    by_key: dict[tuple[str, int, int], dict[str, Any]] = {_dedup_key(r): r for r in existing}
    for r in iss_recs:
        by_key.setdefault(_dedup_key(r), r)
    for r in manual_recs:
        by_key[_dedup_key(r)] = r
    return sorted(by_key.values(), key=lambda r: r["date"])


def _read_iss_payload(client: httpx.Client, cache_dir: Path | None) -> dict[str, Any]:
    cp = (cache_dir / "splits/all.json") if cache_dir else None
    if cp is not None and cp.exists():
        with cp.open(encoding="utf-8") as f:
            return cast(dict[str, Any], json.load(f))
    resp = client.get(SPLITS_PATH)
    resp.raise_for_status()
    data = resp.json()
    if cp is not None:
        cp.parent.mkdir(parents=True, exist_ok=True)
        tmp = cp.with_suffix(cp.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        tmp.replace(cp)
    return cast(dict[str, Any], data)


def ingest(
    tickers: TickersDict,
    manual: list[ManualEntry],
    *,
    output_dir: Path,
    cache_dir: Path | None,
) -> dict[str, int]:
    """Write per-ticker JSONL, return {ticker: row_count} for tickers with rows."""
    output_dir.mkdir(parents=True, exist_ok=True)
    with make_client() as client:
        payload = _read_iss_payload(client, cache_dir)
    iss_per = _parse_iss(payload, tickers)
    manual_per = _parse_manual(manual)
    all_tickers = sorted(set(iss_per) | set(manual_per))

    counts: dict[str, int] = {}
    for ticker in all_tickers:
        out_path = output_dir / f"{ticker}.csv"
        existing = read_records(out_path, casts=SPLIT_CASTS)
        merged = _merge_records(existing, iss_per.get(ticker, []), manual_per.get(ticker, []))
        if merged != existing and merged:
            write_records_atomic(out_path, merged, fieldnames=SPLIT_FIELDS)
        if merged:
            counts[ticker] = len(merged)
            LOG.info("%s: %d split records", ticker, len(merged))
    return counts
