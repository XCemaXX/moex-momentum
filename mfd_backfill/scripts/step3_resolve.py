"""Step 3: offline parse cached HTML+CSV → 3-key match → mfd_ticker_ids.json.

Reads `mfd_backfill/cache/raw/{id}.csv|.html` for every mfd_id in
`mfd_backfill/data/mfd_unique_ids.json`, extracts (Код, ISIN, russian short
name, row count, date range), then resolves each SECID in our universe by
the priority:

    1. Код   (HTML)  — exact SECID match
    2. ISIN  (HTML)  — bridge through MOEX ISS securities map (1 HTTP first run)
    3. Name  (CSV)   — normalized russian short name vs canonical/aliases

On multi-mfd_id collision per SECID at the same priority: pick the record
with the most rows; tie-break by Код presence.

Outputs:
    data/mfd_ticker_ids.json    = {SECID: mfd_id}
    data/mfd_resolve_log.json   = {SECID: {mfd_id, key, kod, isin, name, rows}}

Run:
    python mfd_backfill/scripts/step3_resolve.py
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx

LOG = logging.getLogger("step3_resolve")

MOEX_ISIN_URL = "https://iss.moex.com/iss/engines/stock/markets/shares/securities.json"

# Probed live: HTML stripped to flat text reads as
#   "Код TGKB ISIN RU000A0JNGS7 Номер гос рег ..."
# Код is followed by 1+ space, then a Latin SECID (2..10 chars).
_KOD_RE = re.compile(r"\bКод\s+([A-Z][A-Z0-9_-]{1,9})\b")
_ISIN_RE = re.compile(r"\bISIN\s+([A-Z]{2}[A-Z0-9]{10})\b")

# mfd uses informal tier prefixes ("i", "+") on some short names — strip for match.
_NAME_PREFIX_RE = re.compile(r"^[i+]+", flags=re.IGNORECASE)


def _strip_tags(html: str) -> str:
    s = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", s).strip()


def parse_info_html(html: str) -> dict[str, str | None]:
    text = _strip_tags(html)
    kod = _KOD_RE.search(text)
    isin = _ISIN_RE.search(text)
    return {
        "kod": kod.group(1) if kod else None,
        "isin": isin.group(1) if isin else None,
    }


def _iso_from_yyyymmdd(s: str | None) -> str | None:
    if not s or len(s) != 8 or not s.isdigit():
        return None
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def parse_csv_summary(text: str) -> dict[str, Any]:
    """Lightweight scan: first data row name+date, last data row date, count.
    Returns None values when CSV is empty/header-only."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return {"name": None, "first_date": None, "last_date": None, "rows": 0}
    data = lines[1:]
    first = data[0].split(";")
    last = data[-1].split(";")
    return {
        "name": first[0].strip() if first else None,
        "first_date": _iso_from_yyyymmdd(first[2].strip()) if len(first) > 2 else None,
        "last_date": _iso_from_yyyymmdd(last[2].strip()) if len(last) > 2 else None,
        "rows": len(data),
    }


def normalize_name(s: str | None) -> str:
    if not s:
        return ""
    s = s.strip().lower()
    s = _NAME_PREFIX_RE.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


def fetch_moex_isin_map(cache_path: Path) -> dict[str, str]:
    """One-shot SECID→ISIN pull from MOEX ISS shares-securities endpoint.
    Cached on disk; re-run after the first time is offline."""
    if cache_path.exists():
        cached: dict[str, str] = json.loads(cache_path.read_text(encoding="utf-8"))
        return cached
    LOG.info("fetching MOEX SECID→ISIN map…")
    with httpx.Client(timeout=30.0) as c:
        resp = c.get(MOEX_ISIN_URL, params={"iss.meta": "off"})
        resp.raise_for_status()
    block = resp.json().get("securities", {})
    cols = block.get("columns", [])
    rows = block.get("data", [])
    try:
        i_secid = cols.index("SECID")
        i_isin = cols.index("ISIN")
    except ValueError as exc:
        raise RuntimeError(f"MOEX response missing SECID/ISIN; cols={cols}") from exc
    out: dict[str, str] = {}
    for row in rows:
        sid, isin = row[i_secid], row[i_isin]
        if sid and isin:
            out[sid] = isin
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
    tmp.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(cache_path)
    LOG.info("MOEX securities: %d SECIDs with ISIN", len(out))
    return out


def load_universe(active_p: Path, unavailable_p: Path) -> dict[str, dict[str, Any]]:
    active = json.loads(active_p.read_text(encoding="utf-8"))
    unav: dict[str, dict[str, Any]] = {}
    if unavailable_p.exists():
        with unavailable_p.open(encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                rec = json.loads(line)
                secid = str(rec.pop("secid")).upper()
                unav[secid] = rec
    return {**active, **unav}


def parse_all_records(ids: Iterable[int], cache_dir: Path) -> dict[int, dict[str, Any]]:
    raw_dir = cache_dir / "raw"
    records: dict[int, dict[str, Any]] = {}
    no_csv = no_html = 0
    for mid in ids:
        csv_p = raw_dir / f"{mid}.csv"
        html_p = raw_dir / f"{mid}.html"
        if not csv_p.exists():
            no_csv += 1
            continue  # no name → unmatchable
        rec: dict[str, Any] = {"mfd_id": mid}
        rec.update(parse_csv_summary(csv_p.read_text(encoding="utf-8", errors="replace")))
        if html_p.exists():
            rec.update(parse_info_html(html_p.read_text(encoding="utf-8", errors="replace")))
        else:
            no_html += 1
            rec["kod"] = None
            rec["isin"] = None
        records[mid] = rec
    LOG.info("parsed %d records (missing csv=%d html=%d)", len(records), no_csv, no_html)
    return records


def _tiebreak_better(a: int, b: int, records: dict[int, dict[str, Any]]) -> int:
    """Return the mfd_id with more data; on equal rows prefer Код-bearing."""
    ra, rb = records[a], records[b]
    if ra.get("rows", 0) != rb.get("rows", 0):
        return a if ra["rows"] > rb["rows"] else b
    has_a = 1 if ra.get("kod") else 0
    has_b = 1 if rb.get("kod") else 0
    return a if has_a >= has_b else b


def _build_indices(
    records: dict[int, dict[str, Any]],
) -> tuple[dict[str, list[int]], dict[str, list[int]], dict[str, list[int]]]:
    by_kod: dict[str, list[int]] = {}
    by_isin: dict[str, list[int]] = {}
    by_name: dict[str, list[int]] = {}
    for mid, rec in records.items():
        if rec.get("kod"):
            by_kod.setdefault(rec["kod"], []).append(mid)
        if rec.get("isin"):
            by_isin.setdefault(rec["isin"], []).append(mid)
        nn = normalize_name(rec.get("name"))
        if nn:
            by_name.setdefault(nn, []).append(mid)
    return by_kod, by_isin, by_name


def _pick_best(cands: list[int], records: dict[int, dict[str, Any]]) -> int:
    best = cands[0]
    for c in cands[1:]:
        best = _tiebreak_better(best, c, records)
    return best


def _try_name_match(
    secid: str,
    universe: dict[str, dict[str, Any]],
    by_name: dict[str, list[int]],
) -> list[int]:
    entry = universe[secid]
    names = [entry.get("canonical", "")]
    aliases = entry.get("aliases") or []
    names.extend(aliases)
    out: list[int] = []
    for n in names:
        nn = normalize_name(n)
        if nn and nn in by_name:
            out.extend(by_name[nn])
    return out


def resolve(
    universe: dict[str, dict[str, Any]],
    records: dict[int, dict[str, Any]],
    moex_isin: dict[str, str],
) -> tuple[dict[str, int], dict[str, dict[str, Any]], list[str]]:
    by_kod, by_isin, by_name = _build_indices(records)
    resolved: dict[str, int] = {}
    log: dict[str, dict[str, Any]] = {}
    unresolved: list[str] = []
    for secid in sorted(universe):
        cands: list[int] = by_kod.get(secid, [])
        key = "kod" if cands else None
        if not cands:
            isin = moex_isin.get(secid)
            if isin:
                cands = by_isin.get(isin, [])
                if cands:
                    key = "isin"
        if not cands:
            cands = _try_name_match(secid, universe, by_name)
            if cands:
                key = "name"
        if not cands:
            unresolved.append(secid)
            continue
        mid = _pick_best(cands, records)
        resolved[secid] = mid
        rec = records[mid]
        log[secid] = {
            "mfd_id": mid,
            "key": key,
            "kod": rec.get("kod"),
            "isin": rec.get("isin"),
            "name": rec.get("name"),
            "rows": rec.get("rows"),
            "first_date": rec.get("first_date"),
            "last_date": rec.get("last_date"),
        }
    return resolved, log, unresolved


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Step 3: resolve {SECID: mfd_id} offline.")
    ap.add_argument("--ids", type=Path, default=Path("mfd_backfill/data/mfd_unique_ids.json"))
    ap.add_argument("--cache-dir", type=Path, default=Path("mfd_backfill/cache"))
    ap.add_argument("--tickers", type=Path, default=Path("data/tickers.json"))
    ap.add_argument("--unavailable", type=Path, default=Path("data/tickers_unavailable.jsonl"))
    ap.add_argument("--isin-map", type=Path, default=Path("mfd_backfill/data/moex_isin_map.json"))
    ap.add_argument("--out", type=Path, default=Path("mfd_backfill/data/mfd_ticker_ids.json"))
    ap.add_argument("--log", type=Path, default=Path("mfd_backfill/data/mfd_resolve_log.json"))
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    ids: list[int] = json.loads(args.ids.read_text(encoding="utf-8"))
    universe = load_universe(args.tickers, args.unavailable)
    moex_isin = fetch_moex_isin_map(args.isin_map)
    records = parse_all_records(ids, args.cache_dir)
    resolved, log, unresolved = resolve(universe, records, moex_isin)

    save_json(args.out, resolved)
    save_json(args.log, log)

    by_key = {"kod": 0, "isin": 0, "name": 0}
    for v in log.values():
        by_key[v["key"]] = by_key.get(v["key"], 0) + 1
    LOG.info(
        "resolved %d/%d  (kod=%d isin=%d name=%d)  unresolved=%d",
        len(resolved),
        len(universe),
        by_key["kod"],
        by_key["isin"],
        by_key["name"],
        len(unresolved),
    )
    if unresolved:
        sample = unresolved[:40]
        more = " …" if len(unresolved) > 40 else ""
        LOG.info("unresolved sample: %s%s", sample, more)
    return 0


if __name__ == "__main__":
    sys.exit(main())
