"""Repo-wide dividend invariants. Run against the live data tree.

Catches the class of bugs where two sources record the same payout and both
slip into `monthly_total_returns`, doubling div_return for that month.

Load-bearing: the compute path reads `data/dividends/` as-is and no longer
re-collapses near-duplicates at read time, so this is the only guard that the
tree is deduplicated. Widening the tolerances here weakens the pipeline, it
does not just relax a test.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from storage.records import read_records
from storage.schemas import DIV_CASTS

REPO = Path(__file__).resolve().parents[1]
DIVS = REPO / "data" / "dividends"

DATE_TOL_DAYS = 7
AMOUNT_REL_TOL = 0.01


def _iter_ticker_files() -> list[Path]:
    return sorted(p for p in DIVS.glob("*.csv") if not p.name.startswith("_"))


def _date_diff(a: dict[str, Any], b: dict[str, Any]) -> int:
    return abs(
        (date.fromisoformat(a["registry_close"]) - date.fromisoformat(b["registry_close"])).days
    )


@pytest.mark.parametrize("path", _iter_ticker_files(), ids=lambda p: p.stem)
def test_no_cross_source_near_duplicates(path: Path) -> None:
    """Two records with same currency, |Δdate|≤7d, |Δamount|/max≤1% = same payout."""
    rows = read_records(path, casts=DIV_CASTS)
    dups: list[str] = []
    for i, a in enumerate(rows):
        ad = date.fromisoformat(a["registry_close"])
        aa = float(a["amount"])
        acur = a.get("currency", "RUB")
        for b in rows[i + 1 :]:
            if b.get("currency", "RUB") != acur:
                continue
            if abs((date.fromisoformat(b["registry_close"]) - ad).days) > DATE_TOL_DAYS:
                continue
            ba = float(b["amount"])
            denom = max(abs(aa), abs(ba), 1e-12)
            if abs(aa - ba) / denom <= AMOUNT_REL_TOL:
                dups.append(
                    f"{a['registry_close']}/{aa}/{a.get('source')} ~ "
                    f"{b['registry_close']}/{ba}/{b.get('source')}"
                )
    assert not dups, f"{path.name}: cross-source near-dups: {dups}"


# Two sources disagreeing by more than a rounding error, days apart, is either a
# real multi-tranche payout or one payout recorded twice. Telling them apart needs
# external evidence, so the tree carries a fixed list of the undecided ones. The
# list may only shrink: a new entry means an unreviewed pair reached the data.
#
# Both survivors are 2010-2012 micro-caps whose only witness is the same feed that
# produced the disputed row — smart-lab serves an empty shell for them, dohod has
# no page, and the price series moves +-30% a day, so the ex-date gap says nothing.
# See `task 034`.
UNRESOLVED_PAIRS: frozenset[tuple[str, str, str]] = frozenset(
    {
        ("LNZLP", "2010-05-20", "2010-05-21"),
        ("VRSB", "2012-04-13", "2012-04-16"),
    }
)

CANONICAL_SOURCES = frozenset({"moex_iss", "manual_disclosure"})
RATIO_MIN, RATIO_MAX = 1.01, 50.0


def _curated_amounts() -> set[tuple[str, str, float]]:
    """(ticker, date, amount) a verdict deliberately put into the tree."""
    path = DIVS / "_conflicts_resolved.json"
    out: set[tuple[str, str, float]] = set()
    with path.open(encoding="utf-8") as f:
        verdicts: list[dict[str, Any]] = json.load(f)
    for v in verdicts:
        block = v.get("add") if v.get("action") == "augment" else v.get("to")
        if block:
            out.add((v["ticker"], v["registry_close"], round(float(block["amount"]), 6)))
    return out


def _is_vouched(ticker: str, row: dict[str, Any], curated: set[tuple[str, str, float]]) -> bool:
    if row.get("source") in CANONICAL_SOURCES:
        return True
    amount = round(float(row["amount"]), 6)
    ref = date.fromisoformat(row["registry_close"])
    return any(
        t == ticker
        and abs((date.fromisoformat(d) - ref).days) <= DATE_TOL_DAYS
        and abs(a - amount) <= 1e-6
        for t, d, a in curated
    )


def test_no_unreviewed_cross_source_disagreements() -> None:
    curated = _curated_amounts()
    found: set[tuple[str, str, str]] = set()
    detail: dict[tuple[str, str, str], str] = {}
    for path in _iter_ticker_files():
        ticker = path.stem
        rows = read_records(path, casts=DIV_CASTS)
        for i, a in enumerate(rows):
            for b in rows[i + 1 :]:
                if (a.get("currency") or "RUB") != (b.get("currency") or "RUB"):
                    continue
                if a.get("source") == b.get("source"):
                    continue
                if _date_diff(a, b) > DATE_TOL_DAYS:
                    continue
                aa, ba = float(a["amount"]), float(b["amount"])
                if aa <= 0 or ba <= 0:
                    continue
                ratio = max(aa, ba) / min(aa, ba)
                if not RATIO_MIN <= ratio <= RATIO_MAX:
                    continue
                if _is_vouched(ticker, a, curated) and _is_vouched(ticker, b, curated):
                    continue
                key = (ticker, a["registry_close"], b["registry_close"])
                found.add(key)
                detail[key] = f"{aa}/{a.get('source')} vs {ba}/{b.get('source')} ratio={ratio:.3f}"

    new = found - UNRESOLVED_PAIRS
    assert not new, (
        "unreviewed cross-source disagreement reached the data: "
        + "; ".join(f"{k[0]} {k[1]}~{k[2]} {detail[k]}" for k in sorted(new))
        + ". Resolve it in _conflicts_resolved.json, do not widen the allowlist."
    )
    stale = UNRESOLVED_PAIRS - found
    assert not stale, f"these pairs are resolved and must leave UNRESOLVED_PAIRS: {sorted(stale)}"
