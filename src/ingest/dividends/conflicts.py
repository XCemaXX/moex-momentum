"""Apply manual conflict resolutions (`_conflicts_resolved.json`) to JSONL.

Used to surgically correct stale ISS records or augment with verified
disclosure data. Actions: `replace` | `drop` | `augment`. Idempotent — a
conflict whose target row no longer matches becomes a counted no-op.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from ingest.dividends.types import CONFLICT_ACTIONS
from storage.records import read_records, write_records_atomic
from storage.schemas import DIV_CASTS, DIV_FIELDS

LOG = logging.getLogger(__name__)


def _amount_close(a: float, b: float, rel_tol: float = 1e-6, abs_tol: float = 1e-9) -> bool:
    return abs(a - b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)


def _has_near_duplicate(
    rows: list[dict[str, Any]],
    cand: dict[str, Any],
    *,
    date_tol_days: int = 7,
    amount_rel_tol: float = 0.01,
) -> bool:
    """True if any existing row in same currency matches cand within tolerances."""
    cand_d = date.fromisoformat(cand["registry_close"])
    cand_a = float(cand["amount"])
    cand_cur = cand.get("currency", "RUB")
    for r in rows:
        if r.get("currency", "RUB") != cand_cur:
            continue
        if abs((date.fromisoformat(r["registry_close"]) - cand_d).days) > date_tol_days:
            continue
        ra = float(r["amount"])
        denom = max(abs(ra), abs(cand_a), 1e-12)
        if abs(ra - cand_a) / denom <= amount_rel_tol:
            return True
    return False


@dataclass
class ConflictApplyResult:
    ticker: str
    applied: int
    skipped_no_match: int


def _load_conflicts(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        data: Any = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected JSON array")
    for i, rec in enumerate(data):
        if not isinstance(rec, dict):
            raise ValueError(f"{path}[{i}]: entry is not an object")
        required = ("ticker", "action", "reason")
        for fld in required:
            if not rec.get(fld):
                raise ValueError(f"{path}[{i}]: missing or empty field {fld!r}")
        if rec["action"] not in CONFLICT_ACTIONS:
            raise ValueError(f"{path}[{i}]: action={rec['action']!r} not in {CONFLICT_ACTIONS}")
        # replace/drop/augment mutate JSONL → registry_close required.
        # ignore can be pattern-based → registry_close optional (use applies_to_ym_pattern).
        if rec["action"] != "ignore" and not rec.get("registry_close"):
            raise ValueError(
                f"{path}[{i}]: missing 'registry_close' (required for {rec['action']})"
            )
        if rec["action"] == "replace" and ("from" not in rec or "to" not in rec):
            raise ValueError(f"{path}[{i}]: replace requires 'from' and 'to' blocks")
        if rec["action"] == "drop" and "match" not in rec:
            raise ValueError(f"{path}[{i}]: drop requires 'match' block")
        if rec["action"] == "augment" and "add" not in rec:
            raise ValueError(f"{path}[{i}]: augment requires 'add' block")
    return data


def should_ignore_conflict(
    ignores: list[dict[str, Any]],
    ticker: str,
    ym: str,
    registry_close: str,
    source: str | None,
) -> dict[str, Any] | None:
    """Return the first ignore entry matching this conflict, or None.

    Matching rules:
      - `ticker` must match.
      - If entry has `match.source`, it must equal `source`.
      - If entry has `registry_close`, it must equal the conflict's registry_close.
      - Else if entry has `applies_to_ym_pattern`, it must be "*" or equal ym.
      - Else (no date scope) matches all dates for the ticker.
    """
    for entry in ignores:
        if entry.get("action") != "ignore":
            continue
        if entry.get("ticker") != ticker:
            continue
        match = entry.get("match", {}) or {}
        want_src = match.get("source")
        if want_src is not None and want_src != source:
            continue
        if entry.get("registry_close"):
            if entry["registry_close"] != registry_close:
                continue
        elif entry.get("applies_to_ym_pattern"):
            pat = entry["applies_to_ym_pattern"]
            if pat not in ("*", ym):
                continue
        return entry
    return None


def apply_conflicts_to_jsonl(  # noqa: PLR0912, PLR0915 — 3 action branches × idempotency checks
    path: Path, conflicts: list[dict[str, Any]]
) -> ConflictApplyResult:
    """Apply `replace`/`drop`/`augment` ops to one dividends JSONL atomically."""
    ticker = path.stem
    rows = read_records(path, casts=DIV_CASTS)
    applied = skipped = 0
    for c in conflicts:
        if c["ticker"] != ticker:
            continue
        if c["action"] == "ignore":
            # ignore entries do not mutate JSONL — only filter cascade conflict-flagging
            continue
        reg = c["registry_close"]
        if c["action"] == "replace":
            match = c["from"]
            src = match.get("source", "moex_iss")
            amt = float(match["amount"])
            new_rec = dict(c["to"])
            new_rec["registry_close"] = reg
            new_rec.setdefault("currency", "RUB")
            new_rec["amount"] = float(new_rec["amount"])
            idx = next(
                (
                    i
                    for i, r in enumerate(rows)
                    if r["registry_close"] == reg
                    and r.get("source") == src
                    and _amount_close(float(r["amount"]), amt)
                ),
                None,
            )
            if idx is None:
                if any(
                    r["registry_close"] == reg
                    and r.get("source") == new_rec.get("source")
                    and _amount_close(float(r["amount"]), new_rec["amount"])
                    for r in rows
                ):
                    skipped += 1
                else:
                    LOG.warning(
                        "%s: replace target not found (reg=%s amt=%s src=%s)",
                        ticker,
                        reg,
                        amt,
                        src,
                    )
                    skipped += 1
                continue
            rows[idx] = new_rec
            applied += 1
        elif c["action"] == "drop":
            match = c["match"]
            src = match.get("source", "moex_iss")
            amt = float(match["amount"])
            before = len(rows)
            rows = [
                r
                for r in rows
                if not (
                    r["registry_close"] == reg
                    and r.get("source") == src
                    and _amount_close(float(r["amount"]), amt)
                )
            ]
            removed = before - len(rows)
            if removed:
                applied += removed
            else:
                skipped += 1
        elif c["action"] == "augment":
            new_rec = dict(c["add"])
            new_rec["registry_close"] = reg
            new_rec.setdefault("currency", "RUB")
            new_rec["amount"] = float(new_rec["amount"])
            # Block cross-source near-duplicates: if any existing row in same
            # currency lands within 7d and 1% of this amount, skip — augment
            # would otherwise double-count downstream.
            if _has_near_duplicate(rows, new_rec):
                LOG.warning(
                    "%s: augment near-dup of existing record skipped (reg=%s amt=%s)",
                    ticker,
                    reg,
                    new_rec["amount"],
                )
                skipped += 1
            else:
                rows.append(new_rec)
                applied += 1
    if applied:
        rows.sort(key=lambda r: (r["registry_close"], float(r["amount"])))
        write_records_atomic(path, rows, fieldnames=DIV_FIELDS)
    return ConflictApplyResult(ticker=ticker, applied=applied, skipped_no_match=skipped)


def apply_conflicts_to_universe(
    dividends_dir: Path, conflicts_path: Path
) -> dict[str, ConflictApplyResult]:
    """Apply `_conflicts_resolved.json` across all affected tickers. Idempotent."""
    conflicts = _load_conflicts(conflicts_path)
    by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in conflicts:
        by_ticker[c["ticker"]].append(c)
    out: dict[str, ConflictApplyResult] = {}
    for ticker, ticker_conflicts in by_ticker.items():
        path = dividends_dir / f"{ticker}.csv"
        if not path.exists():
            LOG.warning("conflicts target missing: %s", path)
            continue
        result = apply_conflicts_to_jsonl(path, ticker_conflicts)
        if result.applied or result.skipped_no_match:
            LOG.info(
                "%s: applied=%d skipped_no_match=%d",
                ticker,
                result.applied,
                result.skipped_no_match,
            )
        out[ticker] = result
    return out
