"""Bulk-fetch Tinkoff (tbank.ru) SPA-bootstrap dividend pages for the full
MOEX universe.

Historical pull (task 012 phase 2) and monthly cache refresh. Default: skip
tickers already cached, fetch only the missing. `--refresh`: re-fetch every
ticker, overwriting a snapshot only on a successful fetch that carries a
dividends payload — a network error, 404, or empty page leaves the existing
snapshot intact. Failures summarised in `.fill_cache/tbank/_failures.json`.

Rate limit: 2 req/s. Single attempt per ticker.
"""

from __future__ import annotations

import argparse
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
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--refresh",
        action="store_true",
        help="re-fetch even if cached; overwrite a snapshot only on success",
    )
    args = ap.parse_args()

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

    def _fail(tk: str, status: str, reason: str) -> None:
        failures[tk] = {
            "status": status,
            "reason": reason[:200],
            "ts": datetime.now(UTC).isoformat(),
        }

    try:
        for i, tk in enumerate(tickers, 1):
            cache_file = CACHE_DIR / f"{tk}.html"
            if cache_file.exists() and not args.refresh:
                n_skip += 1
                continue
            url = TbankFetcher.URL_TEMPLATE.format(ticker=tk)
            try:
                r = client.get(url)
            except httpx.HTTPError as exc:
                n_net += 1
                _fail(tk, "error", f"network: {exc}")
                time.sleep(SLEEP_BETWEEN)
                continue
            if r.status_code == 404:
                n_404 += 1
                _fail(tk, "not_found", "tbank 404")
                time.sleep(SLEEP_BETWEEN)
                continue
            if r.status_code != 200:
                _fail(tk, "error", f"http {r.status_code}")
                time.sleep(SLEEP_BETWEEN)
                continue
            # Payload sanity: else broker redirected to a generic stock page.
            # On a miss, keep any prior snapshot — don't overwrite good with bad.
            if _extract_dividends_payload(r.text, tk) is None:
                n_no_payload += 1
                _fail(tk, "no_payload", "investDividends block missing")
            else:
                cache_file.write_text(r.text, encoding="utf-8")
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
