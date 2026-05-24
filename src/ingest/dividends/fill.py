"""Fill dividend gaps from external sources, predecessor-aware.

For each ticker: drop pre-predecessor-cutoff records (manual redomicile bound),
then pull from `fetchers` in tier order, applying `dedup_near_duplicates` after
each tier so same-payout-different-source noise collapses against higher-tier
records.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ingest.dividends.fetchers import DividendFetcher
from ingest.dividends.merge import dedup_near_duplicates
from ingest.dividends.types import DedupKey, dedup_key
from storage.records import read_records
from storage.schemas import DIV_CASTS
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
    n_near_dup_dropped: int
    by_source: dict[str, int]
    records: list[dict[str, Any]]


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


def fill_dividends(
    ticker: str,
    *,
    fetchers: list[DividendFetcher],
    tickers_dict: TickersDict,
    tickers_manual: list[ManualEntry],
    prices_dir: Path,
    dividends_dir: Path,
) -> FillResult:
    """Pull from `fetchers` (in tier order), filter, return new records to merge.

    Each tier sees only keys not already present from higher tiers. Pre-cutoff
    records dropped.
    """
    cutoff = predecessor_cutoff(
        ticker,
        tickers_dict=tickers_dict,
        tickers_manual=tickers_manual,
        prices_dir=prices_dir,
        dividends_dir=dividends_dir,
    )
    existing = read_records(dividends_dir / f"{ticker}.csv", casts=DIV_CASTS)
    seen_keys: set[DedupKey] = {dedup_key(r) for r in existing}

    high_tier_running = list(existing)
    new_records: list[dict[str, Any]] = []
    by_source: dict[str, int] = defaultdict(int)
    n_pre_cutoff = 0

    for f in fetchers:
        try:
            fetched = f.fetch(ticker)
        except Exception as exc:
            LOG.warning("fetcher %s failed for %s: %s", f.source_tag, ticker, exc)
            continue
        filtered, dropped = _filter_by_cutoff(fetched, cutoff)
        n_pre_cutoff += dropped
        tier_new = []
        for r in filtered:
            k = dedup_key(r)
            if k in seen_keys:
                continue
            seen_keys.add(k)
            tier_new.append(r)
        # Fuzzy near-dup pass: same-payout-different-source (e.g. ISS 2023-06-05
        # 563.77 vs dohod 2023-06-05 563.80) must collapse, otherwise sources
        # reporting the same payout inflate the total.
        candidate_union = high_tier_running + tier_new
        _, near_dropped = dedup_near_duplicates(candidate_union)
        near_dup_keys = {dedup_key(r) for r in near_dropped}
        tier_new = [r for r in tier_new if dedup_key(r) not in near_dup_keys]
        new_records.extend(tier_new)
        high_tier_running.extend(tier_new)
        by_source[f.source_tag] += len(tier_new)
        if near_dropped:
            by_source["__near_dup_dropped"] = by_source.get("__near_dup_dropped", 0) + len(
                near_dropped
            )

    return FillResult(
        ticker=ticker,
        cutoff=cutoff,
        n_new=len(new_records),
        n_pre_cutoff_dropped=n_pre_cutoff,
        n_near_dup_dropped=by_source.pop("__near_dup_dropped", 0),
        by_source=dict(by_source),
        records=new_records,
    )
