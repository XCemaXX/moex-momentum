"""Named-series registry for the compare/explorer page (task 20).

A series is one toggleable line. Providers turn on-disk backtest outputs into
`Series`; the chart builder renders them without knowing where they came from.
Adding a strategy = adding a provider — no chart-code change (acceptance #3).

`dims` is an OPEN tag dict (filter/cascade axes for strategies, deferred to
task 21), not fixed fields — benchmarks carry `{}`. `group` is presentation
only: which figure on compare.html the series lands in (task 20 assumed one
figure; the weight-sweep adds a second), kept off `dims` on purpose.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from viz.plotly_charts import load_q_values


@dataclass
class Series:
    id: str
    label: str
    nav: pd.Series  # index Period[M]; rebased to 1.0 at render time
    kind: str  # "strategy" | "benchmark"
    default_visible: bool
    dims: dict[str, str]
    group: str


def q1_signals(*, simple_path: Path, curve_fit_path: Path, group: str = "headline") -> list[Series]:
    """Headline figure: Q1 of both signals + MCFTRR. The two endpoints of the
    weight-sweep (a=1.0 ≡ simple, a=0.9 ≡ curve_fit) — shown clean here."""
    simple = load_q_values(simple_path)
    cf = load_q_values(curve_fit_path)
    base_dims = {"quartile": "Q1", "weighting": "equal", "filter": "none"}
    return [
        Series(
            "q1_simple",
            "Q1 simple",
            simple["Q1"],
            "strategy",
            True,
            {**base_dims, "formula": "simple"},
            group,
        ),
        Series(
            "q1_curve_fit",
            "Q1 curve_fit",
            cf["Q1"],
            "strategy",
            True,
            {**base_dims, "formula": "curve_fit"},
            group,
        ),
        Series("mcftrr", "MCFTRR (benchmark)", cf["MCFTRR"], "benchmark", True, {}, group),
    ]


def weight_sweep(*, sweep_path: Path, group: str = "sweep") -> list[Series]:
    """Sweep figure: 11 Q1 curves for (a·r(12-1)+b·r(6-1))/σ, b=1−a, a=1.0..0.0,
    plus MCFTRR. Second real provider — proves the registry extends without
    touching chart code (acceptance #3)."""
    df = pd.read_csv(sweep_path)
    df["month"] = pd.PeriodIndex(df["month"], freq="M")
    df = df.set_index("month").sort_index()
    a_cols = sorted(
        (c for c in df.columns if c.startswith("a")),
        key=lambda c: float(c[1:]),
        reverse=True,
    )
    out: list[Series] = []
    for c in a_cols:
        a = float(c[1:])
        b = round(1.0 - a, 1)
        # Endpoints coincide with the production signals — flag them.
        note = " (= simple)" if a == 1.0 else " (= curve_fit)" if a == 0.9 else ""
        out.append(
            Series(
                id=f"sweep_{c}",
                label=f"a={a:.1f}{note}",
                nav=df[c],
                kind="strategy",
                default_visible=True,
                dims={
                    "quartile": "Q1",
                    "weighting": "equal",
                    "filter": "none",
                    "formula": "curve_fit",
                    "a": f"{a:.1f}",
                    "b": f"{b:.1f}",
                },
                group=group,
            )
        )
    out.append(
        Series("mcftrr_sweep", "MCFTRR (benchmark)", df["MCFTRR"], "benchmark", True, {}, group)
    )
    return out


__all__ = ["Series", "q1_signals", "weight_sweep"]
