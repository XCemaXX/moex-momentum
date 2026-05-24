"""Bulk-fetch Tinkoff (tbank.ru) SPA-bootstrap dividend pages for the full
MOEX universe.

One-shot historical pull (task 012 phase 2). Idempotent: ticker is skipped
if `.fill_cache/tbank/{T}.html` already exists. Failures are NOT cached, so
re-running this script automatically retries them. Failure summary is
written to `.fill_cache/tbank/_failures.json` after every run.

Rate limit: 2 req/s. Single attempt per ticker.
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
from ingest.dividends.tbank import TbankFetcher, _extract_dividends_payload  # noqa: E402

TICKERS_FILE = ROOT / "data" / "tickers.json"
CACHE_ROOT = ROOT / ".fill_cache"
CACHE_DIR = CACHE_ROOT / "tbank"
FAILURES_PATH = CACHE_DIR / "_failures.json"

SLEEP_BETWEEN = 0.5  # seconds → 2 req/s
PROGRESS_EVERY = 50


def main() -> int:
    tickers = sorted(t_mod.load(TICKERS_FILE).keys())
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    client = httpx.Client(
        timeout=20.0,
        headers={"User-Agent": "Mozilla/5.0 (compatible; moex-momentum/0.1)"},
        follow_redirects=True,
    )

    failures: dict[str, dict[str, str]] = {}
    n_skip = n_ok = n_404 = n_net = n_no_payload = 0
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

    f = TbankFetcher(http_get, cache_dir=CACHE_ROOT)

    try:
        for i, tk in enumerate(tickers, 1):
            cache_file = CACHE_DIR / f"{tk}.html"
            if cache_file.exists():
                n_skip += 1
                continue
            try:
                html = f._fetch_html(tk)
            except Exception as exc:
                failures[tk] = {
                    "status": "error",
                    "reason": str(exc)[:200],
                    "ts": datetime.now(UTC).isoformat(),
                }
            else:
                if html is None:
                    failures[tk] = {
                        "status": "not_found",
                        "reason": "tbank 404",
                        "ts": datetime.now(UTC).isoformat(),
                    }
                else:
                    # Sanity: page must contain a dividends payload, else broker
                    # redirected to a generic stock page (no dividend listing).
                    divs = _extract_dividends_payload(html, tk)
                    if divs is None:
                        n_no_payload += 1
                        failures[tk] = {
                            "status": "no_payload",
                            "reason": "investDividends block missing",
                            "ts": datetime.now(UTC).isoformat(),
                        }
                    else:
                        n_ok += 1
            time.sleep(SLEEP_BETWEEN)
            if i % PROGRESS_EVERY == 0:
                elapsed = time.monotonic() - started
                print(
                    f"  [{i}/{len(tickers)}] ok={n_ok} skip={n_skip} "
                    f"404={n_404} no_payload={n_no_payload} net_err={n_net} "
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
        f"no_payload={n_no_payload} net_err={n_net} total_failures={len(failures)}"
    )
    print(f"failures → {FAILURES_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
