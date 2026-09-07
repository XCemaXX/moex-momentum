"""Bring external dividend amounts onto the stored nominal scale.

Stored rows quote a payout at the share count of its own time. Yahoo and tbank
restate history at today's share count, so every amount before a split is off by
that split's factor and reads as a disagreement rather than the same payout.

Only for feeds that declare `restates_splits`. dohod does not: it restates GMKN
(reporting 1.2 for a 120.0 payout, the 1:100 split of 2024) but leaves T alone
even after T's split — both verified against the price series. Scaling it
wholesale would corrupt the names it leaves alone.

Bonus issues are excluded: feeds do not treat them uniformly, and guessing wrong
would corrupt an amount silently. An unadjusted bonus-issue name surfaces as a
conflict instead.
"""

from __future__ import annotations

from typing import Any


def _share_factor(split: dict[str, Any]) -> float:
    """How the share count changed: 1:N forward → N, N:1 reverse → 1/N."""
    return float(split["after"]) / float(split["before"])


def to_stored_scale(
    rows: list[dict[str, Any]], splits: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Scale each row by the splits that happened after its registry date."""
    applicable = [s for s in splits if s.get("type") != "bonus_issue"]
    if not applicable:
        return rows
    out: list[dict[str, Any]] = []
    for r in rows:
        factor = 1.0
        for s in applicable:
            if r["registry_close"] < s["date"]:
                factor *= _share_factor(s)
        if factor == 1.0:
            out.append(r)
            continue
        rec = dict(r)
        rec["amount"] = float(r["amount"]) * factor
        rec["split_adjusted_back_by"] = factor
        out.append(rec)
    return out
