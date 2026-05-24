"""Cross-source dividend dedup.

Used both by `fill.py` during ingest (collapse the same payout reported by
multiple sources with small date/amount drift) and by ad-hoc cleanup over
existing JSONL files.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from ingest.dividends.types import SOURCE_PRIORITY
from storage.records import read_records, write_records_atomic
from storage.schemas import DIV_CASTS, DIV_FIELDS


def _date_diff_days(a: str, b: str) -> int:
    da = date.fromisoformat(a)
    db = date.fromisoformat(b)
    return abs((da - db).days)


def dedup_near_duplicates(
    records: list[dict[str, Any]],
    *,
    date_tol_days: int = 7,
    amount_rel_tol: float = 0.01,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Drop near-duplicate records across sources reporting the same payout
    with small date/amount differences. Returns (kept, dropped).

    Rule: when two records have `|date diff| ≤ max(date_tol_a, date_tol_b)`
    and `|amount_a - amount_b| / max(amounts) ≤ amount_rel_tol`, keep the
    one with higher SOURCE_PRIORITY. Tie-break: keep the earlier-listed one.

    Same currency only — RUB and USD never collapse.
    """
    by_currency: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for i, r in enumerate(records):
        by_currency[r["currency"]].append((i, r))
    keep_idx: set[int] = set()
    dropped: list[dict[str, Any]] = []
    for _cur, group in by_currency.items():
        group.sort(
            key=lambda x: (
                -SOURCE_PRIORITY.get(x[1].get("source", ""), 0),
                x[0],
            )
        )
        accepted: list[dict[str, Any]] = []
        for _orig_i, r in group:
            is_dup = False
            for acc in accepted:
                if _date_diff_days(r["registry_close"], acc["registry_close"]) > date_tol_days:
                    continue
                a, b = float(r["amount"]), float(acc["amount"])
                denom = max(abs(a), abs(b), 1e-12)
                if abs(a - b) / denom <= amount_rel_tol:
                    is_dup = True
                    break
            if is_dup:
                dropped.append(r)
            else:
                accepted.append(r)
                keep_idx.add(_orig_i)
    kept: list[dict[str, Any]] = [r for i, r in enumerate(records) if i in keep_idx]
    kept.sort(key=lambda r: (r["registry_close"], float(r["amount"])))
    return kept, dropped


def classify_bucket(
    proposed: list[dict[str, Any]],
    existing: list[dict[str, Any]],
    *,
    amount_rel_tol: float = 0.01,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Classify proposed records against existing within a single
    (year-month, currency) bucket. Returns (drops, conflicts).

    All `proposed` and `existing` must already share the same bucket key.
    A "drop" = proposed is a duplicate of existing (incl. multi-tranche
    aggregation in either direction). A "conflict" = genuine disagreement
    requiring user resolution.

    Phases:
      1. Greedy pairwise: each proposed matches first unmatched existing
         within amount_rel_tol → drop.
      2. If all proposed matched → done.
      3. Sum-aggregation check: if unmatched proposed sum matches unmatched
         existing sum (within tol, sum_e > 0) → drop all unmatched. Covers
         both "external feed reports SUM of tranches we store individually"
         and "we store ISS aggregation, external splits into tranches".
      4. Remaining unmatched proposed → conflicts.
    """
    drops: list[dict[str, Any]] = []
    used_existing: set[int] = set()
    unmatched: list[dict[str, Any]] = []
    for cand in proposed:
        ca = float(cand["amount"])
        matched_idx: int | None = None
        for ei, e in enumerate(existing):
            if ei in used_existing:
                continue
            ea = float(e["amount"])
            denom = max(abs(ca), abs(ea), 1e-12)
            if abs(ca - ea) / denom <= amount_rel_tol:
                matched_idx = ei
                break
        if matched_idx is not None:
            used_existing.add(matched_idx)
            drops.append(cand)
        else:
            unmatched.append(cand)
    if not unmatched:
        return drops, []
    sum_p = sum(float(c["amount"]) for c in unmatched)
    sum_e = sum(
        float(existing[i]["amount"]) for i in range(len(existing)) if i not in used_existing
    )
    if sum_e > 0:
        denom = max(abs(sum_p), abs(sum_e), 1e-12)
        if abs(sum_p - sum_e) / denom <= amount_rel_tol:
            drops.extend(unmatched)
            return drops, []
    return drops, unmatched


def cleanup_jsonl_near_duplicates(
    path: Path,
    *,
    date_tol_days: int = 7,
    amount_rel_tol: float = 0.01,
) -> tuple[int, int]:
    """One-shot cleanup of an existing dividends JSONL. Returns (kept, dropped)."""
    rows = read_records(path, casts=DIV_CASTS)
    if not rows:
        return 0, 0
    kept, dropped = dedup_near_duplicates(
        rows,
        date_tol_days=date_tol_days,
        amount_rel_tol=amount_rel_tol,
    )
    if dropped:
        write_records_atomic(path, kept, fieldnames=DIV_FIELDS)
    return len(kept), len(dropped)
