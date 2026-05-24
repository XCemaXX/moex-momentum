"""Shared dividend-domain types and constants."""

from __future__ import annotations

from typing import Any

DedupKey = tuple[str, float, str]


def dedup_key(rec: dict[str, Any]) -> DedupKey:
    return (rec["registry_close"], float(rec["amount"]), rec["currency"])


VALID_SOURCES: frozenset[str] = frozenset(
    {
        "moex_iss",
        "skill_fill_dohod",
        "skill_fill_yahoo",
        "skill_fill_tbank",
        "skill_fill_disclosure",
        "manual_disclosure",
    }
)

# Higher = wins on cross-source near-duplicate.
SOURCE_PRIORITY: dict[str, int] = {
    "moex_iss": 100,
    "manual_disclosure": 95,
    "skill_fill_disclosure": 80,
    "skill_fill_dohod": 70,
    "skill_fill_yahoo": 65,
    "skill_fill_tbank": 63,
}

# Conflict-resolution actions in `_conflicts_resolved.json`.
# `ignore` does NOT modify JSONL — it silences ymconflict-flagging in cascade
# dry-run for verified forever-conflicts (Bucket 1 patterns).
CONFLICT_ACTIONS = frozenset({"replace", "drop", "augment", "ignore"})
