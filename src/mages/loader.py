"""Load data/mages/<YYYY-Qn>.json into quarter records with investable weights.

Only the `shares` group is investable: bonds/fx/fund/otc live in `other` and are
excluded upstream by the parse_mages_index skill. Weights here come from
`pct_shares_only` (shares re-normalized to 100%) and are returned as fractions.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class MagesQuarter:
    quarter: str  # e.g. "2024-Q1"
    period: pd.Period  # the quarter-start month (Period[M]); C1 effect month
    source: str
    weights: dict[str, float]  # ticker -> fraction, sums to 1 over tradable shares
    n_shares: int  # |shares| — N for the phase-2 conviction (mi / mean over N)
    shares: list[dict[str, Any]]  # raw share entries (ticker, canonical, raw_name, pct_shares_only)


def load_quarters(mages_dir: Path) -> list[MagesQuarter]:
    """All quarters, sorted by period. Empty list if the dir has no JSON."""
    out: list[MagesQuarter] = []
    for f in sorted(mages_dir.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        shares = d["shares"]
        total = sum(s["pct_shares_only"] for s in shares)
        if total <= 0:  # no investable shares (all bonds/fx/otc) — would vanish silently
            LOG.warning("mages: %s has no investable shares — skipped", f.name)
            continue
        weights = {s["ticker"]: s["pct_shares_only"] / total for s in shares}
        out.append(
            MagesQuarter(
                quarter=d["quarter"],
                period=pd.Period(d["period"], freq="M"),
                source=d["source"],
                weights=weights,
                n_shares=len(shares),
                shares=shares,
            )
        )
    out.sort(key=lambda q: q.period)
    return out
