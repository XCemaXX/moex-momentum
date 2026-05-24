"""Step 2: bulk raw download per mfd_id.

For each id from `data/mfd_unique_ids.json` fetch two artefacts and dump raw
bytes on disk — parsing is deferred to step 3.

    mfd_backfill/cache/raw/{id}.csv   — /export/handler.ashx OHLCV export
    mfd_backfill/cache/raw/{id}.html  — /marketdata/ticker/?id=N info page
                                     (Russian name, Код [SECID], ISIN)

Network policy (per user spec):
    - 1 rps throttle (mfd ceiling per rusquant convention)
    - No retries. On any failure (HTTP error, non-200, empty body, network
      exception) record the id+endpoint and sleep 10s before continuing.
    - Idempotent: existing cache files skip the HTTP call.

Output (always rewritten at end):
    data/mfd_id_failed.json = {
        "<id>": {"csv": null|"reason", "html": null|"reason"},
        ...
    }
    Only ids with at least one failed endpoint appear.

Run:
    python mfd_backfill/scripts/step2_bulk_download.py
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from _lib import MFD_BASE_URL, MFD_HTTP_TIMEOUT_SECONDS, MFD_USER_AGENT  # noqa: E402

LOG = logging.getLogger("step2_bulk_download")

# SaveFormat/SaveMode/FileName are required (handler returns
# "При создании файла произошла ошибка" otherwise); DateFormat must be
# yyyyMMdd — ISO dashes silently break the export.
EXPORT_URL = (
    "{base}/export/handler.ashx/t{mfd_id}.txt"
    "?Tickers={mfd_id}"
    "&Period=7"
    "&StartDate={start}"
    "&EndDate={end}"
    "&RecordFormat=0"
    "&FieldSeparator=%3B"
    "&DecimalSeparator=."
    "&DateFormat=yyyyMMdd"
    "&TimeFormat=HHmmss"
    "&AddHeader=true"
    "&Fill=false"
    "&SaveFormat=0"
    "&SaveMode=0"
    "&FileName=t{mfd_id}"
)
INFO_URL = "{base}/marketdata/ticker/?id={mfd_id}"

ERROR_BACKOFF_SECONDS = 10.0
THROTTLE_RPS = 1.0


def _ddmmyyyy(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def _throttle(last_call: list[float]) -> None:
    min_gap = 1.0 / THROTTLE_RPS
    now = time.monotonic()
    if last_call:
        wait = min_gap - (now - last_call[0])
        if wait > 0:
            time.sleep(wait)
    last_call[:] = [time.monotonic()]


def _atomic_write_bytes(path: Path, blob: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(blob)
    tmp.replace(path)


def _fetch_one(
    client: httpx.Client, url: str, *, throttle_state: list[float]
) -> tuple[bytes | None, str | None]:
    """Return (bytes, error). On error returns (None, reason). Caller decides
    whether to sleep / log. Throttle is enforced before the actual GET."""
    _throttle(throttle_state)
    try:
        resp = client.get(url)
    except httpx.HTTPError as exc:
        return None, f"http-exc: {type(exc).__name__}: {exc}"
    if resp.status_code != 200:
        return None, f"http-{resp.status_code}"
    if not resp.content:
        return None, "empty-body"
    return resp.content, None


def _save_failures(path: Path, failures: dict[int, dict[str, str | None]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keyed = {str(k): v for k, v in sorted(failures.items())}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(keyed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _load_failures(path: Path) -> dict[int, dict[str, str | None]]:
    if not path.exists():
        return {}
    prior = json.loads(path.read_text(encoding="utf-8"))
    return {int(k): v for k, v in prior.items()}


def _download_endpoint(
    *,
    client: httpx.Client,
    url: str,
    dest: Path,
    label: str,
    mid: int,
    throttle_state: list[float],
) -> tuple[bool, str | None]:
    """Returns (skipped, error). skipped=True → cache hit, no HTTP. error=None on success."""
    if dest.exists():
        return True, None
    blob, err = _fetch_one(client, url, throttle_state=throttle_state)
    if err is None and blob is not None:
        _atomic_write_bytes(dest, blob)
        return False, None
    LOG.warning("id=%d %s FAIL (%s); sleeping %.0fs", mid, label, err, ERROR_BACKOFF_SECONDS)
    time.sleep(ERROR_BACKOFF_SECONDS)
    return False, err


def run(
    ids: list[int],
    *,
    client: httpx.Client,
    cache_dir: Path,
    start: date,
    end: date,
    failures_path: Path,
    save_every: int = 50,
) -> dict[int, dict[str, str | None]]:
    """Download CSV+HTML per id. Returns failure dict; also writes
    `failures_path` periodically and at end (kill-safe resume)."""
    raw_dir = cache_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    failures = _load_failures(failures_path)
    throttle_state: list[float] = []
    start_str = _ddmmyyyy(start)
    end_str = _ddmmyyyy(end)

    csv_done = csv_skipped = html_done = html_skipped = new_failures = 0

    for i, mid in enumerate(ids):
        csv_skip, csv_err = _download_endpoint(
            client=client,
            label="csv",
            mid=mid,
            url=EXPORT_URL.format(base=MFD_BASE_URL, mfd_id=mid, start=start_str, end=end_str),
            dest=raw_dir / f"{mid}.csv",
            throttle_state=throttle_state,
        )
        if csv_skip:
            csv_skipped += 1
        elif csv_err is None:
            csv_done += 1

        html_skip, html_err = _download_endpoint(
            client=client,
            label="html",
            mid=mid,
            url=INFO_URL.format(base=MFD_BASE_URL, mfd_id=mid),
            dest=raw_dir / f"{mid}.html",
            throttle_state=throttle_state,
        )
        if html_skip:
            html_skipped += 1
        elif html_err is None:
            html_done += 1

        if csv_err is not None or html_err is not None:
            failures[mid] = {"csv": csv_err, "html": html_err}
            new_failures += 1
        elif mid in failures:
            failures.pop(mid)

        if (i + 1) % save_every == 0:
            _save_failures(failures_path, failures)
            LOG.info(
                "progress %d/%d  csv:done=%d skip=%d  html:done=%d skip=%d  new-fail=%d",
                i + 1,
                len(ids),
                csv_done,
                csv_skipped,
                html_done,
                html_skipped,
                new_failures,
            )

    _save_failures(failures_path, failures)
    LOG.info(
        "DONE total=%d  csv:done=%d skip=%d  html:done=%d skip=%d  failed-ids=%d",
        len(ids),
        csv_done,
        csv_skipped,
        html_done,
        html_skipped,
        len(failures),
    )
    return failures


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Step 2: bulk raw download per mfd id")
    ap.add_argument("--ids", type=Path, default=Path("mfd_backfill/data/mfd_unique_ids.json"))
    ap.add_argument("--cache-dir", type=Path, default=Path("mfd_backfill/cache"))
    ap.add_argument("--failures", type=Path, default=Path("mfd_backfill/data/mfd_id_failed.json"))
    ap.add_argument("--start", default="2010-01-01")
    ap.add_argument("--end", default=date.today().isoformat())
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    ids: list[int] = json.loads(args.ids.read_text(encoding="utf-8"))
    LOG.info("loaded %d ids from %s", len(ids), args.ids)

    client = httpx.Client(
        timeout=MFD_HTTP_TIMEOUT_SECONDS,
        headers={"User-Agent": MFD_USER_AGENT},
        follow_redirects=True,
    )
    try:
        run(
            ids,
            client=client,
            cache_dir=args.cache_dir,
            start=date.fromisoformat(args.start),
            end=date.fromisoformat(args.end),
            failures_path=args.failures,
        )
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
