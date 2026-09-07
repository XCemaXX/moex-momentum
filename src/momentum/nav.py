"""NAV mechanics shared by every strategy curve.

Quartiles, the top-K fan and the mages tilt all charge
`commission_per_side · Σ|Δw|` on a rebalance and treat a missing per-ticker
return as flat. Keeping the primitives here means a change to the mechanics
lands once instead of once per curve.

The NAV loops themselves stay with their strategies: they differ in rebalance
cadence, weight drift and what diagnostics they emit.
"""

from __future__ import annotations

import logging
import math
from collections import Counter

import pandas as pd

LOG = logging.getLogger(__name__)


def turnover(old_w: dict[str, float], new_w: dict[str, float]) -> float:
    """Target-to-target, so weight drift inside the month is not charged — the
    commission line comes out slightly under what a real book would pay."""
    keys = set(old_w) | set(new_w)
    return sum(abs(new_w.get(k, 0.0) - old_w.get(k, 0.0)) for k in keys)


def gross_return(
    weights: dict[str, float],
    monthly_returns: pd.Series,
    *,
    period: pd.Period,
    label: str,
    misses: list[tuple[str, str, str]] | None = None,
) -> float:
    """Weighted portfolio gross return. Missing per-ticker return → 0%.

    Pass `misses` to collect them for one aggregated WARN per run; without it
    each miss is warned on the spot.
    """
    if not weights:
        return 0.0
    total = 0.0
    for tk, w in weights.items():
        r = monthly_returns.get(tk)
        if r is None or (isinstance(r, float) and math.isnan(r)):
            if misses is None:
                LOG.warning(
                    "missing total_return month=%s ticker=%s portfolio=%s — treated as 0",
                    period,
                    tk,
                    label,
                )
            else:
                misses.append((str(period), str(tk), label))
            continue
        total += w * float(r)
    return total


def warn_missing_returns(misses: list[tuple[str, str, str]], *, label: str) -> None:
    """One line per run instead of one per (month, ticker, portfolio)."""
    if not misses:
        return
    by_portfolio = Counter(q for _, _, q in misses)
    # A single-portfolio caller passes its own label, so the split says nothing.
    split = (
        ""
        if set(by_portfolio) == {label}
        else f", by portfolio {dict(sorted(by_portfolio.items()))}"
    )
    LOG.warning(
        "missing total_return treated as 0 [%s]: %d event(s), %d ticker(s)%s",
        label,
        len(misses),
        len({tk for _, tk, _ in misses}),
        split,
    )
