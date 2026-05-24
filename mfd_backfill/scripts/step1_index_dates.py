"""Step 1: build the list of unique mfd integer IDs that ever traded on MOEX
in the requested year range.

Approach: hit mfd.ru's date-filtered marketdata page for 6 dates/year (10-th
of Jan/Mar/May/Jul/Sep/Nov — avoids long Russian holidays), parse every
`data-id="N"` from the «МосБиржа Акции и ПИФы» group, union across all
snapshots. If a snapshot returns 0 ids, advance +1 day up to 5 times.

Output: data/mfd_unique_ids.json — flat sorted list of ints.

Run:
    python mfd_backfill/scripts/step1_index_dates.py
    python mfd_backfill/scripts/step1_index_dates.py --from-year 2010 --to-year 2025
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from collections.abc import Callable, Iterator
from datetime import date, timedelta
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from _lib import MFD_BASE_URL, MFD_HTTP_TIMEOUT_SECONDS, MFD_USER_AGENT  # noqa: E402

LOG = logging.getLogger("step1_index_dates")

FetchBytes = Callable[[str], bytes | None]

SNAPSHOT_URL = (
    "{base}/marketdata/?id=5&group=16&mode=3&sortHeader=name&sortOrder=1&selectedDate={ddmmyyyy}"
)

_SNAPSHOT_MONTHS = (1, 3, 5, 7, 9, 11)
_SNAPSHOT_DAY = 10
_EMPTY_RETRY_LIMIT = 5

_DATA_ID_RE = re.compile(r'data-id="(\d+)"')


def iter_snapshot_dates(start_year: int, end_year: int) -> Iterator[date]:
    for y in range(start_year, end_year + 1):
        for m in _SNAPSHOT_MONTHS:
            yield date(y, m, _SNAPSHOT_DAY)


def parse_snapshot_ids(html: str) -> set[int]:
    return {int(s) for s in _DATA_ID_RE.findall(html)}


def _decode_html(blob: bytes) -> str:
    if blob.startswith(b"\xef\xbb\xbf"):
        return blob[3:].decode("utf-8", errors="replace")
    try:
        return blob.decode("utf-8")
    except UnicodeDecodeError:
        return blob.decode("windows-1251", errors="replace")


def _ddmmyyyy(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def _cached_fetch(
    url: str,
    *,
    fetch_bytes: FetchBytes,
    cache_dir: Path | None,
    cache_key: str,
) -> bytes | None:
    cache_path: Path | None = None
    if cache_dir is not None:
        cache_path = cache_dir / "snapshots" / cache_key
        if cache_path.exists():
            return cache_path.read_bytes()
    blob = fetch_bytes(url)
    if blob is None or cache_path is None:
        return blob
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
    tmp.write_bytes(blob)
    tmp.replace(cache_path)
    return blob


def fetch_snapshot(
    target: date,
    *,
    fetch_bytes: FetchBytes,
    cache_dir: Path | None,
    retry_limit: int = _EMPTY_RETRY_LIMIT,
) -> tuple[date, set[int]]:
    """Return (actual_date, ids). Advance +1 day on empty up to retry_limit
    times. Raises RuntimeError if all attempts return 0 ids."""
    last_err: str | None = None
    for offset in range(retry_limit + 1):
        d = target + timedelta(days=offset)
        blob = _cached_fetch(
            SNAPSHOT_URL.format(base=MFD_BASE_URL, ddmmyyyy=_ddmmyyyy(d)),
            fetch_bytes=fetch_bytes,
            cache_dir=cache_dir,
            cache_key=f"snap_{d.isoformat()}.html",
        )
        if blob is None:
            last_err = f"{d}: fetch returned None"
            continue
        ids = parse_snapshot_ids(_decode_html(blob))
        if ids:
            if offset > 0:
                LOG.info("snapshot %s: empty, recovered at %s (+%dd)", target, d, offset)
            return d, ids
        last_err = f"{d}: snapshot parsed 0 ids"
    raise RuntimeError(f"snapshot for {target}: {retry_limit + 1} attempts all empty ({last_err})")


def _throttle(rps: float, last_call: list[float]) -> None:
    if rps <= 0:
        return
    min_gap = 1.0 / rps
    now = time.monotonic()
    if last_call:
        wait = min_gap - (now - last_call[0])
        if wait > 0:
            time.sleep(wait)
    last_call[:] = [time.monotonic()]


def collect_unique_ids(
    start_year: int,
    end_year: int,
    *,
    fetch_bytes: FetchBytes,
    cache_dir: Path | None,
    rps: float = 1.0,
    skip_future: date | None = None,
) -> tuple[list[int], list[tuple[date, int]]]:
    cutoff = skip_future if skip_future is not None else date.today()
    ids: set[int] = set()
    per_date: list[tuple[date, int]] = []
    last_call: list[float] = []

    def throttled(url: str) -> bytes | None:
        _throttle(rps, last_call)
        return fetch_bytes(url)

    for target in iter_snapshot_dates(start_year, end_year):
        if target > cutoff:
            break
        try:
            actual, snap_ids = fetch_snapshot(target, fetch_bytes=throttled, cache_dir=cache_dir)
        except RuntimeError as exc:
            LOG.warning("snapshot %s: skip — %s", target, exc)
            per_date.append((target, 0))
            continue
        new = len(snap_ids - ids)
        ids.update(snap_ids)
        per_date.append((actual, len(snap_ids)))
        LOG.info(
            "snapshot %s: %d ids (%d new, total=%d)",
            actual,
            len(snap_ids),
            new,
            len(ids),
        )
    return sorted(ids), per_date


def save_unique_ids(path: Path, ids: list[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(ids, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _make_http_fetch(client: httpx.Client) -> FetchBytes:
    def fetch_bytes(url: str) -> bytes | None:
        try:
            resp = client.get(url)
        except httpx.HTTPError as exc:
            LOG.warning("HTTP error %s: %s", url, exc)
            return None
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            LOG.warning("HTTP %d %s", resp.status_code, url)
            return None
        return resp.content

    return fetch_bytes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Step 1: collect unique mfd IDs")
    ap.add_argument("--from-year", type=int, default=2010)
    ap.add_argument("--to-year", type=int, default=date.today().year)
    ap.add_argument("--output", type=Path, default=Path("mfd_backfill/data/mfd_unique_ids.json"))
    ap.add_argument("--cache-dir", type=Path, default=Path("mfd_backfill/cache"))
    ap.add_argument("--rps", type=float, default=1.0)
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    client = httpx.Client(
        timeout=MFD_HTTP_TIMEOUT_SECONDS,
        headers={"User-Agent": MFD_USER_AGENT},
        follow_redirects=True,
    )
    try:
        ids, per_date = collect_unique_ids(
            args.from_year,
            args.to_year,
            fetch_bytes=_make_http_fetch(client),
            cache_dir=args.cache_dir,
            rps=args.rps,
        )
    finally:
        client.close()

    save_unique_ids(args.output, ids)
    LOG.info(
        "wrote %d unique ids to %s (snapshots: %d)",
        len(ids),
        args.output,
        len(per_date),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
