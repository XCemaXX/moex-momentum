"""Repo-wide dividend invariants. Run against the live data tree.

Catches the class of bugs where two sources record the same payout and both
slip into `monthly_total_returns`, doubling div_return for that month.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from storage.records import read_records
from storage.schemas import DIV_CASTS

REPO = Path(__file__).resolve().parents[1]
DIVS = REPO / "data" / "dividends"

DATE_TOL_DAYS = 7
AMOUNT_REL_TOL = 0.01


def _iter_ticker_files() -> list[Path]:
    return sorted(p for p in DIVS.glob("*.csv") if not p.name.startswith("_"))


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
