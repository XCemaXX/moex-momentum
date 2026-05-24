"""Pending-inclusion candidates — young liquid tickers with no q yet.

Display-only (task 008). Does NOT touch q_values / holdings / backtest numbers.

A candidate at month t is an active share that:
  - has <13 *consecutive* monthly closes ending at t (a gap restarts the count,
    mirroring the universe rule → no universe q computed yet), and
  - is currently trading at t, and
  - clears the universe liquidity floor: its median monthly turnover over the
    current run exceeds `liquidity_floor` (the cut implied by the 100th name).

For age ≥ PENDING_MIN_AGE_FOR_ESTIMATE we also estimate the would-be quartile:
score = r_L / σ_L (geometric-mean return over [run_start+1..t-1], sample stdev
over [run_start+1..t]) — the same per-month form as production, no horizon
scaling — compared against the universe's quartile score boundaries for month t.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import cast

import pandas as pd

from config import PENDING_MIN_AGE_FOR_ESTIMATE, STDEV_DDOF
from momentum.signals import geometric_mean
from momentum.universe import _share_active
from tickers import TickersDict

# 13 closes ending at t make a ticker q-able (age == 12). Below → candidate.
_QABLE_AGE = 12


@dataclass(frozen=True)
class PendingEntry:
    ticker: str
    age: int  # months in the current continuous-close run ending at t (closes - 1)
    status: str  # "early" | "estimated"
    would_be_q: str | None = None
    score: float | None = None
    n: int | None = None  # returns used for r_L (tooltip diagnostics)

    def to_dict(self) -> dict[str, object]:
        out: dict[str, object] = {"ticker": self.ticker, "age": self.age, "status": self.status}
        if self.status == "estimated":
            out["would_be_q"] = self.would_be_q
            out["score"] = self.score
            out["n"] = self.n
        return out


def _quartile_floors(
    scores: pd.Series, quartiles: dict[str, list[str]]
) -> tuple[float, float, float] | None:
    """Lowest score still in Q1, Q2, Q3 — the cut-points to place a candidate."""
    mins: list[float] = []
    for q in ("Q1", "Q2", "Q3"):
        members = quartiles.get(q, [])
        if not members:
            return None
        mins.append(min(float(scores[m]) for m in members))
    return mins[0], mins[1], mins[2]


def _would_be_q(score: float, floors: tuple[float, float, float]) -> str:
    q1_min, q2_min, q3_min = floors
    if score >= q1_min:
        return "Q1"
    if score >= q2_min:
        return "Q2"
    if score >= q3_min:
        return "Q3"
    return "Q4"


def _candidate_score(
    returns_col: pd.Series, first: pd.Period, t: pd.Period
) -> tuple[float, int] | None:
    """(score, n_returns) for r_L/σ_L over the ticker's available window, or None."""
    avail = returns_col[(returns_col.index >= first) & (returns_col.index <= t)].dropna()
    r_window = avail[avail.index <= t - 1]  # skip-month: exclude t
    if len(r_window) < 1 or len(avail) < 2:
        return None
    r_l = geometric_mean(r_window)
    sigma_l = float(avail.std(ddof=STDEV_DDOF))
    if math.isnan(r_l) or not math.isfinite(sigma_l) or sigma_l <= 0:
        return None
    return r_l / sigma_l, len(r_window)


def _current_run(close_col: pd.Series, t: pd.Period) -> tuple[int, pd.Period] | None:
    """(age, run_start) for the unbroken non-NaN-close run ending at t, or None
    if the ticker is not trading at t.

    age = months in the run (closes - 1). A gap restarts the run, mirroring the
    universe's "13 consecutive closes" rule. The backward walk stops once age
    reaches _QABLE_AGE — the run is then q-able and its exact start is irrelevant.
    """
    idx = close_col.index
    if t not in idx:
        return None
    pos = cast(int, idx.get_loc(t))
    if pd.isna(close_col.iat[pos]):
        return None
    start = pos
    while start > 0 and pos - start < _QABLE_AGE:
        prev = start - 1
        if pd.isna(close_col.iat[prev]) or idx[prev] != idx[start] - 1:
            break
        start -= 1
    return pos - start, cast(pd.Period, idx[start])


def compute_month_pending(
    t: pd.Period,
    *,
    returns_panel: pd.DataFrame,
    close_panel: pd.DataFrame,
    value_panel: pd.DataFrame,
    tickers_dict: TickersDict,
    universe: list[str],
    scores: pd.Series,
    quartiles: dict[str, list[str]],
    liquidity_floor: float | None,
) -> list[PendingEntry]:
    """Pending-inclusion candidates for month t, sorted by ticker.

    Returns [] if there is no liquidity floor (no universe cut for the month).
    Eligibility tracks the current continuous-close run (`_current_run`), so a
    gap restarts the age clock — consistent with the universe.
    """
    if liquidity_floor is None:
        return []
    universe_set = set(universe)
    floors = _quartile_floors(scores, quartiles)  # month-constant
    out: list[PendingEntry] = []

    for col in returns_panel.columns:
        tk = str(col)
        if tk in universe_set:
            continue
        run = _current_run(close_panel[tk], t)
        if run is None:
            continue  # not trading at t
        age, run_start = run
        if age >= _QABLE_AGE:
            continue  # 13+ consecutive closes → q is computed in the universe
        if not _share_active(tickers_dict, tk, t):
            continue
        # Median over the current run only — same value convention as the
        # universe floor it is compared against.
        vals = value_panel.loc[(value_panel.index >= run_start) & (value_panel.index <= t), tk]
        med = float(vals.median(skipna=True))
        if math.isnan(med) or med <= liquidity_floor:
            continue

        if age < PENDING_MIN_AGE_FOR_ESTIMATE or floors is None:
            out.append(PendingEntry(ticker=tk, age=age, status="early"))
            continue
        scored = _candidate_score(returns_panel[tk], run_start, t)
        if scored is None:
            out.append(PendingEntry(ticker=tk, age=age, status="early"))
            continue
        score, n = scored
        out.append(
            PendingEntry(
                ticker=tk,
                age=age,
                status="estimated",
                would_be_q=_would_be_q(score, floors),
                score=round(score, 4),
                n=n,
            )
        )

    out.sort(key=lambda e: e.ticker)
    return out
