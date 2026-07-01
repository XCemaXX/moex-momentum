"""Cascade-merge dividends across ISS+dohod (in production CSV) + yahoo +
tbank (from .fill_cache/). Default mode: DRY RUN — no CSV writes.

Per-ticker logic:
  1. Load existing CSV (ISS+dohod+manual entries from prior fills).
  2. Run `fill_dividends` with [YahooFetcher, TbankFetcher] fetchers
     (read-only from .fill_cache/).
  3. For each candidate record fill_dividends proposes:
     - Bucket existing records by (year-month, currency).
     - If candidate's (year-month, currency) already has a record there:
        - amount within 1% → drop (near-dup, fill_dividends already handles).
        - amount >1% different → ymconflict (do not add, surface to report).
     - Otherwise: clean_new (add).
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
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]  # scripts/backfill/ → repo root
sys.path.insert(0, str(ROOT / "src"))

import tickers as t_mod  # noqa: E402
from ingest.dividends.conflicts import should_ignore_conflict  # noqa: E402
from ingest.dividends.fill import fill_dividends  # noqa: E402
from ingest.dividends.merge import classify_bucket  # noqa: E402
from ingest.dividends.tbank import TbankFetcher  # noqa: E402
from ingest.dividends.yahoo import YahooFetcher  # noqa: E402
from storage.records import read_records, write_records_atomic  # noqa: E402
from storage.schemas import DIV_CASTS, DIV_FIELDS, SPLIT_CASTS  # noqa: E402

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

AMOUNT_TOL = 0.01  # 1%


def _no_fetch(url: str) -> str | None:
    # cache-only mode
    return None


def _bucket_key(rec: dict[str, Any]) -> tuple[str, str]:
    return (rec["registry_close"][:7], rec["currency"])


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

    # Never book a declared-but-unpaid dividend: brokers list future record
    # dates, but total-return may only include a payout once its date has passed.
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

    # Splits per ticker → ISS records amounts at nominal-at-time; Yahoo/tbank
    # back-apply splits. For each pre-split external record, divide by the
    # cumulative split factor of all splits that came AFTER the record date,
    # bringing the amount into ISS-compatible nominal-at-time convention.
    splits_by_ticker: dict[str, list[dict[str, Any]]] = {}
    for p in SPLITS_DIR.glob("*.csv"):
        rows = read_records(p, casts=SPLIT_CASTS)
        if rows:
            splits_by_ticker[p.stem.upper()] = sorted(rows, key=lambda r: r["date"])

    def _ratio_for_split(s: dict[str, Any]) -> float:
        # ratio that Yahoo/tbank applied: new_amount = old_amount / ratio.
        # For forward split before:1 after:N: shares ×N, per-share amount /N → ratio = N
        # For reverse split before:N after:1: shares /N, per-share amount ×N → ratio = 1/N
        # For bonus_issue before:1 after:N: same as forward.
        return float(s["after"]) / float(s["before"])

    def _adjust_external(rows: list[dict[str, Any]], ticker: str) -> list[dict[str, Any]]:
        splits = splits_by_ticker.get(ticker.upper())
        if not splits:
            return rows
        # bonus_issue treated differently by Yahoo (par value unchanged), skip.
        applicable = [s for s in splits if s.get("type") != "bonus_issue"]
        if not applicable:
            return rows
        out: list[dict[str, Any]] = []
        for r in rows:
            factor = 1.0
            for s in applicable:
                if r["registry_close"] < s["date"]:
                    factor *= _ratio_for_split(s)
            rec = r
            if factor != 1.0:
                rec = dict(r)
                rec["amount"] = float(r["amount"]) * factor
                rec["split_adjusted_back_by"] = factor
            out.append(rec)
        return out

    yf_real = YahooFetcher(_no_fetch, cache_dir=CACHE_ROOT)
    tb_real = TbankFetcher(_no_fetch, cache_dir=CACHE_ROOT)

    class _Filtered:
        def __init__(self, inner: Any, blacklist: set[str]) -> None:
            self._inner = inner
            self._blacklist = blacklist
            self.source_tag = inner.source_tag

        def fetch(self, ticker: str) -> list[dict[str, Any]]:
            tk = ticker.upper()
            if tk in self._blacklist:
                return []
            return _adjust_external(self._inner.fetch(ticker), tk)

    yf: Any = _Filtered(yf_real, yahoo_blacklist)
    tb: Any = _Filtered(tb_real, tbank_blacklist)

    fetcher_map = {"yahoo": yf, "tbank": tb}
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
            fetchers=fetchers,  # type: ignore[arg-type]
            tickers_dict=tickers_dict,
            tickers_manual=manual,
            prices_dir=PRICES_DIR,
            dividends_dir=DIV_DIR,
        )
        candidates = [r for r in result.records if r["registry_close"] <= today_iso]
        if since_ym:
            candidates = [r for r in candidates if r["registry_close"][:7] >= since_ym]
        if not candidates:
            continue

        # Bucket existing by (ym, currency). May have multiple records per bucket
        # (real two-tranche payouts).
        existing_buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for r in existing:
            existing_buckets[_bucket_key(r)].append(r)
        proposed_buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for cand in candidates:
            proposed_buckets[_bucket_key(cand)].append(cand)

        clean_new: list[dict[str, Any]] = []
        for key, cands in proposed_buckets.items():
            collisions = existing_buckets.get(key, [])
            if not collisions:
                clean_new.extend(cands)
                continue
            _drops, conflicts = classify_bucket(
                cands,
                collisions,
                amount_rel_tol=AMOUNT_TOL,
            )
            for cand in conflicts:
                if should_ignore_conflict(
                    ignore_entries,
                    ticker=tk,
                    ym=key[0],
                    registry_close=cand["registry_close"],
                    source=cand.get("source"),
                ):
                    ignored_count += 1
                    continue
                ymconflict_candidates.append(
                    {
                        "ticker": tk,
                        "ym": key[0],
                        "currency": key[1],
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
                            float(cand["amount"]) / float(e["amount"])
                            if float(e["amount"]) > 0
                            else float("inf")
                            for e in collisions
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
