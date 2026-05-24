"""Step 3a: extend `data/moex_isin_map.json` with delisted SECIDs via the
paginated ISS securities endpoint.

The board-scoped endpoint used in step 3
(`/iss/engines/stock/markets/shares/securities.json`) is current-only
(~487 SECIDs). This wider endpoint walks ALL stock-shares securities,
delisted included (~3000 total).

GET https://iss.moex.com/iss/securities.json?engine=stock&market=shares
    Pages of 100 rows; pass `start=N` to advance. Empty `data` ends the loop.
    Columns include `secid`, `isin`, `shortname`, `emitent_title`, `is_traded`.

Merge policy: existing values in `data/moex_isin_map.json` win on collision —
never overwrite the active-board ISIN with a possibly-stale delisted one.

Run:
    python mfd_backfill/scripts/step3a_extend_isin_map.py
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

import httpx

LOG = logging.getLogger("step3a_extend_isin_map")

URL = "https://iss.moex.com/iss/securities.json"
PAGE_SIZE = 100
THROTTLE_RPS = 5.0


def _throttle(state: list[float]) -> None:
    min_gap = 1.0 / THROTTLE_RPS
    now = time.monotonic()
    if state:
        wait = min_gap - (now - state[0])
        if wait > 0:
            time.sleep(wait)
    state[:] = [time.monotonic()]


def fetch_page(client: httpx.Client, start: int) -> tuple[list[list[Any]], list[str]]:
    resp = client.get(
        URL,
        params={
            "engine": "stock",
            "market": "shares",
            "iss.meta": "off",
            "start": start,
        },
    )
    resp.raise_for_status()
    block = resp.json().get("securities", {})
    return block.get("data", []), block.get("columns", [])


def collect_all(client: httpx.Client) -> dict[str, str]:
    """Walk pages until empty. Returns {SECID: ISIN} (only rows with both set)."""
    state: list[float] = []
    start = 0
    out: dict[str, str] = {}
    while True:
        _throttle(state)
        rows, cols = fetch_page(client, start)
        if not rows:
            break
        try:
            i_sec = cols.index("secid")
            i_isin = cols.index("isin")
        except ValueError as exc:
            raise RuntimeError(f"ISS response missing secid/isin; cols={cols}") from exc
        page_new = 0
        for r in rows:
            sec = r[i_sec]
            isin = r[i_isin]
            if sec and isin and sec not in out:
                out[sec] = isin
                page_new += 1
        LOG.info("start=%d rows=%d unique=%d total=%d", start, len(rows), page_new, len(out))
        start += PAGE_SIZE
    return out


def merge_keep_existing(base: dict[str, str], extra: dict[str, str]) -> tuple[dict[str, str], int]:
    """Add new SECIDs from `extra` to `base`. Returns (merged, n_added)."""
    added = 0
    merged = dict(base)
    for k, v in extra.items():
        if k not in merged:
            merged[k] = v
            added += 1
    return merged, added


def save_json(path: Path, data: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Step 3a: extend ISIN map with delisted SECIDs")
    ap.add_argument("--map", type=Path, default=Path("mfd_backfill/data/moex_isin_map.json"))
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    base: dict[str, str] = {}
    if args.map.exists():
        base = json.loads(args.map.read_text(encoding="utf-8"))
    LOG.info("starting from %d existing SECIDs in %s", len(base), args.map)

    with httpx.Client(timeout=30.0) as client:
        extra = collect_all(client)

    merged, added = merge_keep_existing(base, extra)
    save_json(args.map, merged)
    LOG.info("merged: %d → %d (+%d) entries", len(base), len(merged), added)
    return 0


if __name__ == "__main__":
    sys.exit(main())
