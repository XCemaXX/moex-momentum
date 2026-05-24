"""Bulk-fetch Yahoo Finance v8 chart dividends for the full MOEX universe.

One-shot historical pull (task 012 phase 2). Idempotent: ticker is skipped
if `.fill_cache/yahoo/{T}.json` already exists. Failures are NOT cached, so
re-running this script automatically retries them. Failure summary is
written to `.fill_cache/yahoo/_failures.json` after every run.

Rate limit: 2 req/s. Single attempt per ticker — no in-script retry loops
(per memory: escalate network failures immediately).
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]  # scripts/backfill/ → repo root
sys.path.insert(0, str(ROOT / "src"))

import tickers as t_mod  # noqa: E402
from ingest.dividends.yahoo import YahooFetcher  # noqa: E402

TICKERS_FILE = ROOT / "data" / "tickers.json"
CACHE_ROOT = ROOT / ".fill_cache"
CACHE_DIR = CACHE_ROOT / "yahoo"
FAILURES_PATH = CACHE_DIR / "_failures.json"

SLEEP_BETWEEN = 0.5  # seconds → 2 req/s
PROGRESS_EVERY = 50


def main() -> int:
    tickers = sorted(t_mod.load(TICKERS_FILE).keys())
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    client = httpx.Client(
        timeout=15.0,
        headers={"User-Agent": "Mozilla/5.0 (compatible; moex-momentum/0.1)"},
        follow_redirects=True,
    )

    failures: dict[str, dict[str, str]] = {}
    n_skip = n_ok = n_404 = n_net = n_empty = 0
    started = time.monotonic()

    def http_get(url: str) -> str | None:
        nonlocal n_404, n_net
        try:
            r = client.get(url)
        except httpx.HTTPError as exc:
            n_net += 1
            raise RuntimeError(f"network: {exc}") from exc
        if r.status_code == 404:
            n_404 += 1
            return None
        if r.status_code != 200:
            raise RuntimeError(f"http {r.status_code}")
        return r.text

    f = YahooFetcher(http_get, cache_dir=CACHE_ROOT)

    try:
        for i, tk in enumerate(tickers, 1):
            cache_file = CACHE_DIR / f"{tk}.json"
            if cache_file.exists():
                n_skip += 1
                continue
            try:
                rows = f.fetch(tk)
            except Exception as exc:
                failures[tk] = {
                    "status": "error",
                    "reason": str(exc)[:200],
                    "ts": datetime.now(UTC).isoformat(),
                }
            else:
                if not cache_file.exists():
                    # 404 path: fetcher returned [] without caching.
                    failures[tk] = {
                        "status": "not_found",
                        "reason": "yahoo 404",
                        "ts": datetime.now(UTC).isoformat(),
                    }
                elif not rows:
                    n_empty += 1
                    failures[tk] = {
                        "status": "empty",
                        "reason": "no dividend events",
                        "ts": datetime.now(UTC).isoformat(),
                    }
                else:
                    n_ok += 1
            time.sleep(SLEEP_BETWEEN)
            if i % PROGRESS_EVERY == 0:
                elapsed = time.monotonic() - started
                print(
                    f"  [{i}/{len(tickers)}] ok={n_ok} skip={n_skip} "
                    f"404={n_404} empty={n_empty} net_err={n_net} "
                    f"({elapsed:.0f}s)",
                    flush=True,
                )
    finally:
        client.close()
        FAILURES_PATH.write_text(
            json.dumps(failures, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    print(
        f"\nDONE: ok={n_ok} skip(cached)={n_skip} 404={n_404} "
        f"empty={n_empty} net_err={n_net} total_failures={len(failures)}"
    )
    print(f"failures → {FAILURES_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
