"""Cascade-merge dividends across ISS+dohod (in production CSV) + yahoo +
tbank (from .fill_cache/). Default mode: DRY RUN — no CSV writes.

Per-ticker logic:
  1. Load existing CSV (ISS+dohod+manual entries from prior fills).
  2. Run `fill_dividends` with [YahooFetcher, TbankFetcher] fetchers
     (read-only from .fill_cache/). It reconciles against the stored rows and
     returns what is safe to add plus what disagrees.
  3. Add `records`; surface `conflicts` to the report unless an `ignore` verdict
     in `_conflicts_resolved.json` silences them.
  4. Counts and conflict candidates go to two reports.

Dry-run outputs:
  - validate_with_raw/reports/cascade_dryrun.md       summary, top contributors
  - validate_with_raw/reports/cascade_conflicts.json  proposals for _conflicts_resolved.json

With `--apply`: actually writes CSVs (skips ymconflict candidates — user
must resolve those manually in _conflicts_resolved.json first).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]  # scripts/backfill/ → repo root
sys.path.insert(0, str(ROOT / "src"))

import tickers as t_mod  # noqa: E402
from ingest.dividends.fetchers import DividendFetcher  # noqa: E402
from ingest.dividends.fill import fill_dividends  # noqa: E402
from ingest.dividends.merge import DATE_TOL_DAYS  # noqa: E402
from ingest.dividends.tbank import TbankFetcher  # noqa: E402
from ingest.dividends.yahoo import YahooFetcher  # noqa: E402
from storage.records import read_records, write_records_atomic  # noqa: E402
from storage.schemas import DIV_CASTS, DIV_FIELDS  # noqa: E402

TICKERS_FILE = ROOT / "data" / "tickers.json"
MANUAL_FILE = ROOT / "data" / "tickers_manual.json"
DIV_DIR = ROOT / "data" / "dividends"
SPLITS_DIR = ROOT / "data" / "splits"
CACHE_ROOT = ROOT / ".fill_cache"
PRICES_DIR = ROOT / "data" / "prices_iss"
BLACKLIST_FILE = DIV_DIR / "_external_blacklist.json"
CONFLICTS_RESOLVED_FILE = DIV_DIR / "_conflicts_resolved.json"

REPORT_MD = ROOT / "validate_with_raw" / "reports" / "cascade_dryrun.md"
CONFLICTS_JSON = ROOT / "validate_with_raw" / "reports" / "cascade_conflicts.json"


def _no_fetch(url: str) -> str | None:
    # cache-only mode
    return None


def _in_window(rows: list[dict[str, Any]], since_ym: str | None) -> list[dict[str, Any]]:
    if not since_ym:
        return list(rows)
    return [r for r in rows if r["registry_close"][:7] >= since_ym]


def _neighbours(existing: list[dict[str, Any]], cand: dict[str, Any]) -> list[dict[str, Any]]:
    """Stored rows the candidate collides with, for the report."""
    cur = cand.get("currency") or "RUB"
    ref = date.fromisoformat(cand["registry_close"])
    return [
        e
        for e in existing
        if (e.get("currency") or "RUB") == cur
        and abs((date.fromisoformat(e["registry_close"]) - ref).days) <= DATE_TOL_DAYS
    ]


def main() -> int:  # noqa: PLR0912, PLR0915 — one-shot script, linear orchestration
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true", help="actually write CSVs")
    p.add_argument(
        "--ticker", action="append", default=[], help="limit to specific tickers (repeatable)"
    )
    p.add_argument(
        "--sources",
        default="yahoo,tbank",
        help="comma-separated subset of {yahoo,tbank} in cascade order",
    )
    p.add_argument(
        "--months",
        type=int,
        default=0,
        help="only reconcile candidates with registry_close in the last N months "
        "(0 = full history). Monthly runs scope this so settled history is not re-opened.",
    )
    args = p.parse_args()

    today_iso = date.today().isoformat()

    # Recent-window cutoff (YYYY-MM). The yahoo/tbank caches are static snapshots,
    # so a full-history re-derive keeps re-surfacing already-curated old records.
    since_ym: str | None = None
    if args.months > 0:
        today = date.today()
        y, m = today.year, today.month - args.months
        while m <= 0:
            m += 12
            y -= 1
        since_ym = f"{y:04d}-{m:02d}"

    tickers_dict = t_mod.load(TICKERS_FILE)
    manual = t_mod.load_manual(MANUAL_FILE)
    selected = sorted(args.ticker) if args.ticker else sorted(tickers_dict.keys())

    yahoo_blacklist: set[str] = set()
    tbank_blacklist: set[str] = set()
    if BLACKLIST_FILE.exists():
        bl = json.loads(BLACKLIST_FILE.read_text(encoding="utf-8"))
        for tk, entry in bl.get("tickers", {}).items():
            excl = entry.get("exclude", [])
            if "yahoo" in excl:
                yahoo_blacklist.add(tk.upper())
            if "tbank" in excl:
                tbank_blacklist.add(tk.upper())

    ignore_entries: list[dict[str, Any]] = []
    if CONFLICTS_RESOLVED_FILE.exists():
        all_conflicts = json.loads(CONFLICTS_RESOLVED_FILE.read_text(encoding="utf-8"))
        ignore_entries = [c for c in all_conflicts if c.get("action") == "ignore"]
    ignored_count = 0

    yf_real = YahooFetcher(_no_fetch, cache_dir=CACHE_ROOT)
    tb_real = TbankFetcher(_no_fetch, cache_dir=CACHE_ROOT)

    class _Filtered:
        # Must mirror every DividendFetcher attribute: fill_dividends reads them
        # off the object it is handed, not off the wrapped one.
        def __init__(self, inner: DividendFetcher, blacklist: set[str]) -> None:
            self._inner = inner
            self._blacklist = blacklist
            self.source_tag = inner.source_tag
            self.restates_splits = inner.restates_splits

        def fetch(self, ticker: str) -> list[dict[str, Any]]:
            tk = ticker.upper()
            if tk in self._blacklist:
                return []
            return list(self._inner.fetch(ticker))

    fetcher_map: dict[str, DividendFetcher] = {
        "yahoo": _Filtered(yf_real, yahoo_blacklist),
        "tbank": _Filtered(tb_real, tbank_blacklist),
    }
    source_order = [s.strip() for s in args.sources.split(",") if s.strip()]
    unknown = [s for s in source_order if s not in fetcher_map]
    if unknown:
        raise SystemExit(f"unknown --sources {unknown}; valid: {sorted(fetcher_map)}")
    fetchers = [fetcher_map[s] for s in source_order]

    totals: Counter[str] = Counter()
    per_source_added: Counter[str] = Counter()
    ymconflict_candidates: list[dict[str, Any]] = []
    tickers_touched: list[dict[str, Any]] = []

    for tk in selected:
        existing = read_records(DIV_DIR / f"{tk}.csv", casts=DIV_CASTS)
        result = fill_dividends(
            tk,
            fetchers=fetchers,
            tickers_dict=tickers_dict,
            tickers_manual=manual,
            prices_dir=PRICES_DIR,
            dividends_dir=DIV_DIR,
            splits_dir=SPLITS_DIR,
            ignore_entries=ignore_entries,
        )
        clean_new = _in_window(result.records, since_ym)

        # `fill_dividends` reconciled against stored rows already: `records`
        # collide with nothing, `conflicts` need a verdict. Collisions are
        # recomputed here for the report only.
        ignored_count += result.n_conflicts_ignored
        for cand in _in_window(result.conflicts, since_ym):
            ym = cand["registry_close"][:7]
            collisions = _neighbours(existing, cand)
            ymconflict_candidates.append(
                {
                    "ticker": tk,
                    "ym": ym,
                    "currency": cand.get("currency") or "RUB",
                    "existing": [
                        {
                            "registry_close": e["registry_close"],
                            "amount": float(e["amount"]),
                            "source": e.get("source"),
                        }
                        for e in collisions
                    ],
                    "proposed": {
                        "registry_close": cand["registry_close"],
                        "amount": float(cand["amount"]),
                        "source": cand.get("source"),
                        "registry_close_source": cand.get("registry_close_source"),
                    },
                    "ratio_max": max(
                        (
                            float(cand["amount"]) / float(e["amount"])
                            if float(e["amount"]) > 0
                            else float("inf")
                            for e in collisions
                        ),
                        default=float("inf"),
                    ),
                }
            )

        if not clean_new:
            continue

        totals["tickers"] += 1
        totals["records"] += len(clean_new)
        for r in clean_new:
            per_source_added[r["source"]] += 1
        tickers_touched.append(
            {
                "ticker": tk,
                "n_clean_new": len(clean_new),
                "n_ymconflict": sum(1 for c in ymconflict_candidates if c["ticker"] == tk),
                "by_source": Counter(r["source"] for r in clean_new),
            }
        )

        if args.apply and clean_new:
            merged = existing + clean_new
            merged.sort(key=lambda r: (r["registry_close"], float(r["amount"])))
            write_records_atomic(DIV_DIR / f"{tk}.csv", merged, fieldnames=DIV_FIELDS)

    # Reports
    lines: list[str] = []
    mode = "APPLIED" if args.apply else "DRY RUN"
    lines.append(f"# Cascade merge — {mode} (task 012 phase 3)")
    lines.append("")
    lines.append(f"Cascade order: ISS (in JSONL) → dohod (in JSONL) → {' → '.join(source_order)}.")
    window = f"since {since_ym}" if since_ym else "full history"
    lines.append(f"Window: {window}, through {today_iso}.")
    lines.append("Same-(year-month, currency) collisions: amount within 1% → near-dup")
    lines.append("(skip), else → ymconflict (NOT added in either mode, listed below).")
    lines.append("")
    lines.append("## Headline")
    lines.append("")
    lines.append(f"- Tickers with new clean records: **{totals['tickers']}**")
    lines.append(f"- Clean new records to add: **{totals['records']}**")
    lines.append(
        f"- ymconflict candidates: **{len(ymconflict_candidates)}** (require manual review)"
    )
    lines.append(
        f"- Conflicts silenced via `_conflicts_resolved.json` ignore entries: **{ignored_count}**"
    )
    lines.append("")
    lines.append("### Clean new records by source")
    for src, cnt in per_source_added.most_common():
        lines.append(f"- {src}: {cnt}")
    lines.append("")
    lines.append("### Top tickers by clean-new-record count")
    lines.append("")
    lines.append("| Ticker | new records | ymconflicts | by source |")
    lines.append("|---|---:|---:|---|")
    for r in sorted(tickers_touched, key=lambda x: -x["n_clean_new"])[:30]:
        by_src = ", ".join(f"{s}={n}" for s, n in r["by_source"].most_common())
        lines.append(f"| {r['ticker']} | {r['n_clean_new']} | {r['n_ymconflict']} | {by_src} |")
    lines.append("")

    lines.append("## YM-conflict candidates")
    lines.append("")
    lines.append("Same (year, month, currency) bucket; existing record(s) and proposed")
    lines.append("disagree by more than 1%. **NOT auto-merged.** User must add a `replace`,")
    lines.append("`drop`, or `augment` entry to `data/dividends/_conflicts_resolved.json` to")
    lines.append("resolve, then re-run with `--apply`.")
    lines.append("")
    lines.append(f"Top 30 by amount ratio (full list → `{CONFLICTS_JSON.name}`):")
    lines.append("")
    lines.append("| Ticker | ym | existing | proposed | ratio |")
    lines.append("|---|---|---|---|---:|")
    for c in sorted(ymconflict_candidates, key=lambda x: -x["ratio_max"])[:30]:
        ex = c["existing"][0]
        pr = c["proposed"]
        ex_s = f"{ex['amount']:g} ({ex['source']})"
        pr_s = f"{pr['amount']:g} ({pr['source']})"
        lines.append(f"| {c['ticker']} | {c['ym']} | {ex_s} | {pr_s} | {c['ratio_max']:.2f} |")
    lines.append("")

    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    CONFLICTS_JSON.write_text(
        json.dumps(
            ymconflict_candidates,
            ensure_ascii=False,
            indent=2,
            default=lambda o: o.most_common() if isinstance(o, Counter) else str(o),
        ),
        encoding="utf-8",
    )
    print(f"wrote {REPORT_MD}", file=sys.stderr)
    print(f"wrote {CONFLICTS_JSON}", file=sys.stderr)
    print(
        f"\nmode={mode} clean_tickers={totals['tickers']} "
        f"clean_records={totals['records']} ymconflicts={len(ymconflict_candidates)} "
        f"ignored={ignored_count}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
