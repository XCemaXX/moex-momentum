"""Bootstrap `data/tickers.json` from MOEX ISS + optional merge of external aliases.

Contract:
- `bootstrap(existing, client, cache_dir, today)` → new `TickersDict`. Does not mutate
  `existing`. Pulls: listing → securities/{SECID} → changeover.
  Does not touch `tickers_manual.json`.
- `merge_external_aliases(tickers, seed)` → new `TickersDict` with extended `aliases`.

All HTTP responses are cached in `cache_dir` (if set). This is critical: parsing and
validation run *after* the raw payload is on disk, so a validation failure does not
cost thousands of repeat requests to ISS. For force-refetch — delete the contents of
`cache_dir`.

listing.json pagination is drained until an empty block (no total field).
listing row grain = (SECID, BOARDID); we dedupe to unique SECIDs before processing.
Delisted/renamed SECIDs return HTTP 200 — liveness is read from `boards`.
"""

from __future__ import annotations

import copy
import json
import logging
import re
import time
from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast

import httpx

from config import ISS_BASE_URL, ISS_HTTP_TIMEOUT_SECONDS
from tickers import Board, Rebrand, TickerEntry, TickersDict

LOG = logging.getLogger(__name__)

LISTING_PATH = "/history/engines/stock/markets/shares/listing.json"
CHANGEOVER_PATH = "/history/engines/stock/markets/shares/securities/changeover.json"

EQUITY_TYPES = frozenset({"common_share", "preferred_share"})
PLACEHOLDER_NEW_SECID = "XXXXXX"
DELISTED_GAP_DAYS = 7
ISS_REQUEST_DELAY_S = 0.03
PROGRESS_LOG_EVERY = 200

# Legacy listing rows where SECID = ISIN (CC + 9 alphanumerics + check digit) —
# duplicates of real tickers, drop them.
ISIN_SHAPED_SECID_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}\d$")


def make_iss_client() -> httpx.Client:
    return httpx.Client(
        base_url=ISS_BASE_URL,
        timeout=ISS_HTTP_TIMEOUT_SECONDS,
        params={"iss.meta": "off"},
        headers={"User-Agent": "moex-momentum/0.1"},
    )


def _cache_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / f"{key}.json"


def _cached_get(
    client: httpx.Client,
    url_path: str,
    *,
    params: dict[str, str] | None = None,
    cache_dir: Path | None,
    cache_key: str,
    force: bool = False,
) -> dict[str, Any] | None:
    """GET with on-disk cache. Returns `None` for 404 (not cached).

    `force` re-fetches even on a cache hit (still rewrites the cache). The cache
    has no TTL, so a monthly refresh over an old cache would otherwise replay a
    stale ISS snapshot — wrong board windows, false delisted_after.
    """
    if cache_dir is not None and not force:
        cp = _cache_path(cache_dir, cache_key)
        if cp.exists():
            with cp.open(encoding="utf-8") as f:
                return cast(dict[str, Any], json.load(f))
    resp = client.get(url_path, params=params or {})
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    data = resp.json()
    if cache_dir is not None:
        cp = _cache_path(cache_dir, cache_key)
        cp.parent.mkdir(parents=True, exist_ok=True)
        tmp = cp.with_suffix(cp.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        tmp.replace(cp)
    return cast(dict[str, Any], data)


def _drain_listing(
    client: httpx.Client,
    cache_dir: Path | None,
    skip_secids: frozenset[str] = frozenset(),
    *,
    force: bool = False,
) -> list[str]:
    """Unique SECIDs with at least one row having non-empty history_from/till."""
    seen: set[str] = set()
    start = 0
    while True:
        data = _cached_get(
            client,
            LISTING_PATH,
            params={"start": str(start)},
            cache_dir=cache_dir,
            cache_key=f"listing/page_{start:05d}",
            force=force,
        )
        if data is None:
            break
        block = data["securities"]
        cols: list[str] = block["columns"]
        rows: list[list[Any]] = block["data"]
        if not rows:
            break
        secid_idx = cols.index("SECID")
        from_idx = cols.index("history_from")
        till_idx = cols.index("history_till")
        for row in rows:
            if row[from_idx] is None or row[till_idx] is None:
                continue
            secid = str(row[secid_idx]).upper()
            if ISIN_SHAPED_SECID_RE.match(secid):
                continue
            if secid in skip_secids:
                continue
            seen.add(secid)
        start += len(rows)
    return sorted(seen)


def _pivot_kv(block: Mapping[str, Any]) -> dict[str, str]:
    cols: list[str] = block["columns"]
    rows: list[list[Any]] = block["data"]
    name_idx = cols.index("name")
    value_idx = cols.index("value")
    out: dict[str, str] = {}
    for row in rows:
        k = row[name_idx]
        v = row[value_idx]
        if not k:
            continue
        out[str(k)] = "" if v is None else str(v)
    return out


def _parse_boards(block: Mapping[str, Any]) -> list[Board]:
    """Boards for phase-4 price fallback: only market='shares' AND engine='stock'.

    Filters out REPO (RPMA/RPMO/RPEU/...), liquidity-provider (LIQR/LIQB), negotiated
    (PSEQ/PTEQ/PSRP/...), CLMR/STMR/SDMR-style — all service books without normal
    daily price history. Also requires a non-empty `history_from` (actual trading).
    """
    cols: list[str] = block["columns"]
    rows: list[list[Any]] = block["data"]
    out: list[Board] = []
    for row in rows:
        rec = dict(zip(cols, row, strict=True))
        if rec.get("market") != "shares" or rec.get("engine") != "stock":
            continue
        if not rec.get("history_from"):
            continue
        b: Board = {
            "board": str(rec["boardid"]),
            "is_primary": bool(rec.get("is_primary")),
            "history_from": str(rec["history_from"]),
        }
        if rec.get("history_till"):
            b["history_till"] = str(rec["history_till"])
        out.append(b)
    return out


def _delisted_after(boards: list[Board], today: date) -> str | None:
    for b in boards:
        if not b.get("is_primary"):
            continue
        ht = b.get("history_till")
        if not ht:
            return None
        try:
            last = date.fromisoformat(ht)
        except ValueError:
            return None
        if last < today - timedelta(days=DELISTED_GAP_DAYS):
            return ht
        return None
    return None


def _merge_aliases(existing: list[str], new: Iterable[str], canonical: str) -> list[str]:
    seen = {canonical.casefold()} | {a.casefold() for a in existing}
    out = list(existing)
    for raw in new:
        if not raw:
            continue
        n = raw.strip()
        if not n:
            continue
        key = n.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(n)
    return out


def _add_rebrand(entry: TickerEntry, rebrand: Rebrand) -> None:
    history = entry.setdefault("history", [])
    key = (rebrand["prev_ticker"], rebrand["renamed"])
    for h in history:
        if (h["prev_ticker"], h["renamed"]) == key:
            return
    history.append(rebrand)
    history.sort(key=lambda h: h["renamed"])


def _drain_changeover(
    client: httpx.Client, cache_dir: Path | None, *, force: bool = False
) -> list[tuple[str, str, str]]:
    data = _cached_get(
        client, CHANGEOVER_PATH, cache_dir=cache_dir, cache_key="changeover", force=force
    )
    assert data is not None, "changeover.json must not return 404"
    block = data["changeover"]
    cols: list[str] = block["columns"]
    rows: list[list[Any]] = block["data"]
    date_idx = cols.index("action_date")
    old_idx = cols.index("old_secid")
    new_idx = cols.index("new_secid")
    out: list[tuple[str, str, str]] = []
    for row in rows:
        new = row[new_idx]
        if new == PLACEHOLDER_NEW_SECID:
            continue
        out.append((str(row[date_idx]), str(row[old_idx]), str(new)))
    return out


def bootstrap(
    existing: TickersDict,
    *,
    client: httpx.Client,
    cache_dir: Path | None = None,
    today: date | None = None,
    skip_secids: frozenset[str] = frozenset(),
    force_refresh: bool = False,
) -> TickersDict:
    """ISS-refresh: canonical/aliases (NAME+LATNAME) /boards/history (changeover) /delisted_after.

    Idempotent. Existing manual aliases and manual history (source=manual) are
    preserved — _merge_aliases/_add_rebrand dedupe them.

    `cache_dir` — if set, all HTTP responses are cached. A repeat run over the cache
    makes no network requests. `force_refresh` re-fetches past the cache (no TTL) —
    use it for monthly refreshes so board windows / delisted_after stay current.
    """
    today = today or date.today()
    result: TickersDict = copy.deepcopy(existing)

    secids = _drain_listing(client, cache_dir, skip_secids=skip_secids, force=force_refresh)
    LOG.info("listing: %d unique SECIDs", len(secids))

    for i, secid in enumerate(secids):
        if i and i % PROGRESS_LOG_EVERY == 0:
            LOG.info("securities: %d / %d", i, len(secids))
        cache_hit = (
            not force_refresh
            and cache_dir is not None
            and _cache_path(cache_dir, f"securities/{secid}").exists()
        )
        if i and not cache_hit:
            time.sleep(ISS_REQUEST_DELAY_S)
        payload = _cached_get(
            client,
            f"/securities/{secid}.json",
            cache_dir=cache_dir,
            cache_key=f"securities/{secid}",
            force=force_refresh,
        )
        if payload is None:
            LOG.warning("secid %s: 404, skip", secid)
            continue
        desc = _pivot_kv(payload["description"])
        type_ = desc.get("TYPE", "")
        if type_ not in EQUITY_TYPES:
            continue
        shortname = desc.get("SHORTNAME", "").strip()
        if not shortname:
            LOG.warning("secid %s: empty SHORTNAME, skip", secid)
            continue
        entry = result.setdefault(secid, cast(TickerEntry, {}))
        if not entry.get("canonical"):
            entry["canonical"] = shortname
        entry["type"] = "share"
        entry["aliases"] = _merge_aliases(
            entry.get("aliases", []),
            [desc.get("NAME", ""), desc.get("LATNAME", "")],
            entry["canonical"],
        )
        entry["boards"] = _parse_boards(payload["boards"])
        last = _delisted_after(entry["boards"], today)
        if last:
            entry["delisted_after"] = last
        elif "delisted_after" in entry:
            del entry["delisted_after"]

    LOG.info("dictionary: %d shares after TYPE filter", len(result))

    changes = _drain_changeover(client, cache_dir, force=force_refresh)
    LOG.info("changeover: %d records", len(changes))
    applied = 0
    for action_date, old, new in changes:
        target = result.get(new)
        if target is None:
            continue
        _add_rebrand(
            target,
            {"prev_ticker": old, "renamed": action_date, "source": "iss_changeover"},
        )
        applied += 1
    LOG.info("changeover: %d applied to known shares", applied)
    return result


def merge_external_aliases(
    tickers: TickersDict,
    seed: Mapping[str, Mapping[str, Any]],
) -> TickersDict:
    """Extends `aliases` from an external seed (`merged_aliases.json` schema).

    SECIDs missing from the current dictionary are ignored (often delisted tickers
    from the old universe — wiring them in is a separate problem).
    """
    result = copy.deepcopy(tickers)
    for secid, ext in seed.items():
        if secid.startswith("_"):
            continue
        entry = result.get(secid)
        if entry is None:
            continue
        canonical = entry.get("canonical", "")
        names = list(ext.get("names", []))
        former = list(ext.get("former_names", []))
        entry["aliases"] = _merge_aliases(
            entry.get("aliases", []),
            names + former,
            canonical,
        )
    return result
