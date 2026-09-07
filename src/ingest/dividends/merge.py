"""Cross-source dividend reconciliation.

`reconcile` is the single decision point for "is this the same payout". Ingest
calls it; nothing else needs to.

Stored rows are immovable. A fetched row that restates a stored payout is a
duplicate; one that disagrees beyond tolerance is a conflict for
`data/dividends/_conflicts_resolved.json`, never a silent append. Appending
instead of asking is how one payout ended up recorded twice a day apart and
counted twice in `monthly_total_returns`.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from ingest.dividends.types import SOURCE_PRIORITY

DATE_TOL_DAYS = 7
AMOUNT_REL_TOL = 0.01


def _date_diff_days(a: str, b: str) -> int:
    return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)


def _amounts_match(a: float, b: float, tol: float) -> bool:
    denom = max(abs(a), abs(b), 1e-12)
    return abs(a - b) / denom <= tol


def _currency(rec: dict[str, Any]) -> str:
    # Every source here quotes MOEX listings, so an unset field is RUB.
    return str(rec.get("currency") or "RUB")


def classify_bucket(
    proposed: list[dict[str, Any]],
    existing: list[dict[str, Any]],
    *,
    amount_rel_tol: float = AMOUNT_REL_TOL,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Classify proposed records against colliding existing ones. Returns
    (drops, conflicts).

    A "drop" = proposed restates something already stored (incl. multi-tranche
    aggregation in either direction). A "conflict" = genuine disagreement
    requiring user resolution. Nothing is ever accepted here: a proposed row
    that collides with stored data is the operator's call, not the code's.

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
            if _amounts_match(ca, float(e["amount"]), amount_rel_tol):
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
    if sum_e > 0 and _amounts_match(sum_p, sum_e, amount_rel_tol):
        drops.extend(unmatched)
        return drops, []
    return drops, unmatched


def _keep_by_priority(
    rows: list[dict[str, Any]],
    date_tol_days: int,
    amount_rel_tol: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Collapse rows describing one payout, keeping the highest-priority source.

    Tie-break on the original order, so the result does not depend on fetcher
    ordering beyond SOURCE_PRIORITY.
    """
    ordered = sorted(
        enumerate(rows),
        key=lambda x: (-SOURCE_PRIORITY.get(str(x[1].get("source", "")), 0), x[0]),
    )
    accepted: list[dict[str, Any]] = []
    kept_idx: set[int] = set()
    dropped: list[dict[str, Any]] = []
    for i, r in ordered:
        dup = any(
            _date_diff_days(r["registry_close"], a["registry_close"]) <= date_tol_days
            and _amounts_match(float(r["amount"]), float(a["amount"]), amount_rel_tol)
            for a in accepted
        )
        if dup:
            dropped.append(r)
        else:
            accepted.append(r)
            kept_idx.add(i)
    return [r for i, r in enumerate(rows) if i in kept_idx], dropped


def _clusters(
    proposed: list[dict[str, Any]],
    existing: list[dict[str, Any]],
    date_tol_days: int,
) -> list[tuple[list[dict[str, Any]], list[dict[str, Any]]]]:
    """Group rows into date-neighbourhoods, single-linkage on `date_tol_days`.

    Judging a whole neighbourhood at once is what lets an aggregate reported by
    one source collapse against the tranches stored from another.
    """
    marked = [(r["registry_close"], True, r) for r in proposed]
    marked += [(r["registry_close"], False, r) for r in existing]
    marked.sort(key=lambda x: (x[0], x[1]))
    out: list[tuple[list[dict[str, Any]], list[dict[str, Any]]]] = []
    cur_p: list[dict[str, Any]] = []
    cur_e: list[dict[str, Any]] = []
    last: str | None = None
    for dt, is_proposed, r in marked:
        if last is not None and _date_diff_days(dt, last) > date_tol_days:
            if cur_p:
                out.append((cur_p, cur_e))
            cur_p, cur_e = [], []
        (cur_p if is_proposed else cur_e).append(r)
        last = dt
    if cur_p:
        out.append((cur_p, cur_e))
    return out


def reconcile(
    existing: list[dict[str, Any]],
    proposed: list[dict[str, Any]],
    *,
    date_tol_days: int = DATE_TOL_DAYS,
    amount_rel_tol: float = AMOUNT_REL_TOL,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Split `proposed` against `existing` into (accepted, duplicates, conflicts).

    Same currency only — RUB and USD never collapse.
    """
    by_cur_existing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in existing:
        by_cur_existing[_currency(r)].append(r)
    by_cur_proposed: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in proposed:
        by_cur_proposed[_currency(r)].append(r)

    accepted: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for cur, rows in by_cur_proposed.items():
        for cl_prop, cl_exist in _clusters(rows, by_cur_existing.get(cur, []), date_tol_days):
            # Collapse agreeing sources first. `classify_bucket` pairs proposed to
            # existing one-to-one, so a second source restating the same payout
            # would otherwise be reported as a disagreement.
            keep, drop = _keep_by_priority(cl_prop, date_tol_days, amount_rel_tol)
            duplicates.extend(drop)
            if cl_exist:
                drops, confl = classify_bucket(keep, cl_exist, amount_rel_tol=amount_rel_tol)
                duplicates.extend(drops)
                conflicts.extend(confl)
            else:
                accepted.extend(keep)
    accepted.sort(key=lambda r: (r["registry_close"], float(r["amount"])))
    return accepted, duplicates, conflicts
