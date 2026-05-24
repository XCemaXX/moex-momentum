"""Membership-swap experiment for task 017.

Goal: isolate the universe/membership effect from the return data. Build
per-quartile NAV two ways over the same window, under identical mechanics
(equal-weight, gross, drop-missing tickers):

  - "ours"  : our own quartile memberships (data/momentum/curve_fit/holdings)
  - "ref"   : the author's published memberships (agent_context/reference_quartiles.json)

Both use OUR monthly return panel. Any NAV gap is therefore purely the
membership difference, not a return-data or weighting difference.

Limitation: the author's memberships exist only from 2022-03 (text export
limit). The disputed 2013-2020 period has no reference membership, so this
experiment cannot probe it directly.

Outputs (persisted, separate folder):
  data/momentum/ref_membership/q_values_ours.csv
  data/momentum/ref_membership/q_values_ref.csv
  data/momentum/ref_membership/coverage.csv     # how many ref tickers exist in our panel
One-shot research script. Gross returns only (no commission) for a clean
membership contrast; the on-disk curve_fit/q_values.csv differs by commission
and missing-as-zero handling, a small effect noted in the report.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from momentum.universe import load_panel

ROOT = Path(__file__).resolve().parents[1]
MONTHLY_DIR = ROOT / "data" / "momentum" / "monthly"
OUR_HOLDINGS = ROOT / "data" / "momentum" / "curve_fit" / "holdings"
REF_FILE = ROOT / "agent_context" / "reference_quartiles.json"
OUT_DIR = ROOT / "data" / "momentum" / "ref_membership"
Q_LABELS = ["Q1", "Q2", "Q3", "Q4"]


def _quartile_return(
    returns_panel: pd.DataFrame, month: pd.Period, tickers: list[str]
) -> tuple[float, int, int]:
    """Equal-weight mean return over tickers present in the panel for `month`.

    Returns (mean_return, n_present, n_total). Missing tickers are dropped
    (renormalized), not treated as zero — more honest for a membership the
    author had data for but we may not.
    """
    if month not in returns_panel.index:
        return 0.0, 0, len(tickers)
    row = returns_panel.loc[month]
    vals = [float(row[t]) for t in tickers if t in row.index and pd.notna(row[t])]
    if not vals:
        return 0.0, 0, len(tickers)
    return sum(vals) / len(vals), len(vals), len(tickers)


def _load_our_memberships() -> dict[pd.Period, dict[str, list[str]]]:
    out: dict[pd.Period, dict[str, list[str]]] = {}
    for p in sorted(OUR_HOLDINGS.glob("*.json")):
        period = pd.Period(p.stem, freq="M")
        out[period] = json.loads(p.read_text(encoding="utf-8"))
    return out


def _load_ref_memberships() -> dict[pd.Period, dict[str, list[str]]]:
    raw = json.loads(REF_FILE.read_text(encoding="utf-8"))
    out: dict[pd.Period, dict[str, list[str]]] = {}
    for month, obj in raw.items():
        out[pd.Period(month, freq="M")] = {q: list(obj.get(q, [])) for q in Q_LABELS}
    return out


def _build_nav(
    returns_panel: pd.DataFrame,
    memberships: dict[pd.Period, dict[str, list[str]]],
    months: list[pd.Period],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """NAV path + coverage. Composition as-of close of month t earns month t+1
    return (same timing as the engine). `months` is the inclusive NAV index;
    months[0] is the NAV=1.0 base."""
    nav = {q: 1.0 for q in Q_LABELS}
    nav_rows: list[dict[str, object]] = [{"month": str(months[0]), **dict(nav)}]
    cov_rows: list[dict[str, object]] = []
    for m in months[1:]:
        prev = m - 1
        comp = memberships.get(prev)
        if comp is None:
            nav_rows.append({"month": str(m), **dict(nav)})
            continue
        cov: dict[str, object] = {"month": str(m)}
        for q in Q_LABELS:
            r, n_present, n_total = _quartile_return(returns_panel, m, comp.get(q, []))
            nav[q] *= 1.0 + r
            cov[f"{q}_present"] = n_present
            cov[f"{q}_total"] = n_total
        nav_rows.append({"month": str(m), **dict(nav)})
        cov_rows.append(cov)
    return (
        pd.DataFrame(nav_rows).set_index("month"),
        pd.DataFrame(cov_rows).set_index("month") if cov_rows else pd.DataFrame(),
    )


def main() -> None:
    returns_panel, _, _ = load_panel(MONTHLY_DIR)
    ref = _load_ref_memberships()
    ours = _load_our_memberships()

    ref_months = sorted(ref)
    # Common NAV window: from first ref month to last panel month covered.
    start = ref_months[0]
    end = max(m for m in returns_panel.index if m <= ref_months[-1] + 1)
    months = [m for m in returns_panel.index if start <= m <= end]

    nav_ref, cov = _build_nav(returns_panel, ref, months)
    nav_ours, _ = _build_nav(returns_panel, ours, months)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    nav_ours.to_csv(OUT_DIR / "q_values_ours.csv")
    nav_ref.to_csv(OUT_DIR / "q_values_ref.csv")
    cov.to_csv(OUT_DIR / "coverage.csv")

    # Console summary for the report.
    print(f"window {months[0]} .. {months[-1]} ({len(months)} months)")
    print("\n=== final NAV (gross, base=1.0 at start) ===")
    print(f"{'Q':>3} {'ours':>9} {'ref':>9} {'ref/ours':>9}")
    for q in Q_LABELS:
        o = float(nav_ours[q].iloc[-1])
        r = float(nav_ref[q].iloc[-1])
        print(f"{q:>3} {o:>9.3f} {r:>9.3f} {r / o:>9.3f}")

    print("\n=== ref-membership coverage (present/total, mean across months) ===")
    for q in Q_LABELS:
        pres = cov[f"{q}_present"].astype(float).mean()
        tot = cov[f"{q}_total"].astype(float).mean()
        print(f"{q}: {pres:.1f}/{tot:.1f}  ({100 * pres / tot:.1f}% of ref names in our panel)")


if __name__ == "__main__":
    main()
