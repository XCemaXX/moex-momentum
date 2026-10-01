"""Fill dividend gaps from external sources, predecessor-aware.

For each ticker: drop pre-predecessor-cutoff, not-yet-paid and verdict-dropped
records, then pull from every fetcher and hand the whole batch to `reconcile`,
which decides what joins the stored rows. This module does not judge payout identity itself.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from config import FOREIGN_CURRENCY_TICKERS
from ingest.dividends.conflicts import drop_matches, should_ignore_conflict
from ingest.dividends.fetchers import DividendFetcher
from ingest.dividends.merge import reconcile
from ingest.dividends.scale import to_stored_scale
from storage.records import read_records
from storage.schemas import DIV_CASTS, SPLIT_CASTS
from tickers import ManualEntry, TickersDict

LOG = logging.getLogger(__name__)


def predecessor_cutoff(
    ticker: str,
    *,
    tickers_dict: TickersDict,
    tickers_manual: list[ManualEntry],
    prices_dir: Path,
    dividends_dir: Path,
) -> str | None:
    """Earliest valid `registry_close` (ISO) for fill. None = no predecessor.

    Policy (set 2026-05-12): only `tickers_manual.json` with explicit
    `type=redomicile`, `new_secid==ticker`, `old_secid != new_secid` triggers
    a cutoff. These mark **legal-entity changes with long trading gaps** (X5,
    YDEX, HEAD, VKCO) where predecessor and successor are different securities.

    `iss_changeover` history (MTSS←MTSI, SFIN←EPLN, UPRO←EONR, T←TCSG, etc.)
    is **NOT a cutoff signal**: gaps are <30 days, predecessor and successor
    are the same company under a renamed SECID. Bridge them.

    `prices_dir` / `dividends_dir` are accepted for forward compatibility but
    currently unused — kept in the signature so callers don't need to change
    if policy evolves.
    """
    del tickers_dict, prices_dir, dividends_dir  # reserved for future use
    cutoffs: list[str] = []
    for rec in tickers_manual:
        if (
            rec.get("type") == "redomicile"
            and rec.get("new_secid") == ticker
            and rec.get("old_secid") != rec.get("new_secid")
        ):
            cutoffs.append(rec["renamed"])
    return max(cutoffs) if cutoffs else None


@dataclass
class FillResult:
    ticker: str
    cutoff: str | None
    n_new: int
    n_pre_cutoff_dropped: int
    n_duplicates_dropped: int
    n_future_dropped: int
    n_foreign_dropped: int
    n_verdict_dropped: int
    n_conflicts_ignored: int
    by_source: dict[str, int]
    records: list[dict[str, Any]]
    conflicts: list[dict[str, Any]]


def _filter_by_cutoff(
    records: list[dict[str, Any]], cutoff: str | None
) -> tuple[list[dict[str, Any]], int]:
    if not cutoff:
        return records, 0
    kept, dropped = [], 0
    for r in records:
        if r["registry_close"] < cutoff:
            dropped += 1
        else:
            kept.append(r)
    return kept, dropped


def _drop_ignored(
    conflicts: list[dict[str, Any]], ignores: list[dict[str, Any]], ticker: str
) -> tuple[list[dict[str, Any]], int]:
    unresolved = [
        c
        for c in conflicts
        if not should_ignore_conflict(
            ignores,
            ticker=ticker,
            ym=c["registry_close"][:7],
            registry_close=c["registry_close"],
            source=c.get("source"),
        )
    ]
    return unresolved, len(conflicts) - len(unresolved)


def fill_dividends(
    ticker: str,
    *,
    fetchers: list[DividendFetcher],
    tickers_dict: TickersDict,
    tickers_manual: list[ManualEntry],
    prices_dir: Path,
    dividends_dir: Path,
    splits_dir: Path | None = None,
    verdicts: list[dict[str, Any]] | None = None,
    today: date | None = None,
) -> FillResult:
    """Fetch, filter, and reconcile against stored rows.

    `records` are the rows safe to append. `conflicts` are rows that collide
    with stored data and need a verdict in `_conflicts_resolved.json` — they are
    reported, never written.

    `splits_dir` only matters for fetchers that declare `restates_splits`.
    `verdicts` are the entries of `_conflicts_resolved.json`. A `drop` removes
    the matching fetched row here too, or a phantom we don't store would come
    back as new. An `ignore` silences a settled conflict that would otherwise be
    re-reported every run; it never filters new rows.
    """
    cutoff = predecessor_cutoff(
        ticker,
        tickers_dict=tickers_dict,
        tickers_manual=tickers_manual,
        prices_dir=prices_dir,
        dividends_dir=dividends_dir,
    )
    existing = read_records(dividends_dir / f"{ticker}.csv", casts=DIV_CASTS)
    today_iso = (today or date.today()).isoformat()
    splits: list[dict[str, Any]] = []
    if splits_dir is not None:
        splits = read_records(splits_dir / f"{ticker}.csv", casts=SPLIT_CASTS)

    verdicts = verdicts or []
    drops = [v for v in verdicts if v["action"] == "drop" and v["ticker"] == ticker]
    ignores = [v for v in verdicts if v["action"] == "ignore"]

    proposed: list[dict[str, Any]] = []
    n_pre_cutoff = 0
    n_verdict_dropped = 0
    n_future = 0
    n_foreign = 0
    for f in fetchers:
        try:
            fetched = f.fetch(ticker)
        except Exception as exc:
            LOG.warning("fetcher %s failed for %s: %s", f.source_tag, ticker, exc)
            continue
        if splits and f.restates_splits:
            fetched = to_stored_scale(fetched, splits)
        filtered, dropped = _filter_by_cutoff(fetched, cutoff)
        n_pre_cutoff += dropped
        for r in filtered:
            # A board recommendation is not a payout. dohod lists them with a
            # plain future date, indistinguishable from a settled record.
            if r["registry_close"] > today_iso:
                n_future += 1
                continue
            # A non-RUB payout on a ticker that never declares one means the feed
            # matched a foreign company on the ticker letters.
            if (r.get("currency") or "RUB") != "RUB" and ticker not in FOREIGN_CURRENCY_TICKERS:
                n_foreign += 1
                continue
            # Before reconcile: a phantom must not win a cluster and push out a
            # real lower-tier row as its duplicate.
            if any(drop_matches(d, r) for d in drops):
                n_verdict_dropped += 1
                continue
            proposed.append(r)

    accepted, duplicates, conflicts = reconcile(existing, proposed)
    conflicts, n_ignored = _drop_ignored(conflicts, ignores, ticker)
    by_source: dict[str, int] = defaultdict(int)
    for r in accepted:
        by_source[str(r.get("source", ""))] += 1

    return FillResult(
        ticker=ticker,
        cutoff=cutoff,
        n_new=len(accepted),
        n_pre_cutoff_dropped=n_pre_cutoff,
        n_duplicates_dropped=len(duplicates),
        n_future_dropped=n_future,
        n_foreign_dropped=n_foreign,
        n_verdict_dropped=n_verdict_dropped,
        n_conflicts_ignored=n_ignored,
        by_source=dict(by_source),
        records=accepted,
        conflicts=conflicts,
    )
