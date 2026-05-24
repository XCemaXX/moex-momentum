"""Phase 10 — plotly chart builders.

HTML rendering tests live in test_site_builder.py (Phase 11). The shared
plotly bundle SHA/size guards stayed here as they apply to the committed
artefact, not the renderer.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math
from pathlib import Path
from typing import Any

import pandas as pd

from storage.records import write_records_atomic
from storage.schemas import Q_VALUES_FIELDS
from viz.plotly_charts import (
    load_q_values,
    plot_q1_minus_mcftrr,
    plot_q1_q4_dynamics,
    plot_quartile_transitions,
    transition_sankey_payloads,
)
from viz.site_builder import PLOTLY_BUNDLE_SHA256


def _sample_q_values() -> pd.DataFrame:
    months = pd.period_range("2022-01", "2022-12", freq="M")
    return pd.DataFrame(
        {
            "Q1": [1.0 * 1.05**i for i in range(len(months))],
            "Q2": [1.0 * 1.02**i for i in range(len(months))],
            "Q3": [1.0 * 1.00**i for i in range(len(months))],
            "Q4": [1.0 * 0.98**i for i in range(len(months))],
            "MCFTRR": [1.0 * 1.01**i for i in range(len(months))],
        },
        index=months,
    )


def _write_q_csv(path: Path, df: pd.DataFrame) -> None:
    rows = [
        {"month": str(period), **{k: float(v) for k, v in row.items()}}
        for period, row in df.iterrows()
    ]
    write_records_atomic(path, rows, fieldnames=Q_VALUES_FIELDS)


def test_quartile_transitions_is_sankey() -> None:
    holdings = {
        "2022-01": {"Q1": ["A"], "Q2": ["B"], "Q3": [], "Q4": []},
        "2022-02": {"Q1": ["B"], "Q2": ["A"], "Q3": [], "Q4": []},
    }
    fig = plot_quartile_transitions(holdings)
    sk = fig.data[0]
    assert sk.type == "sankey"
    # 10 nodes: Q1..Q4,Новые (left, 0..4) + Q1..Q4,Выбыли (right, 5..9).
    assert list(sk.node.label) == [
        "Q1",
        "Q2",
        "Q3",
        "Q4",
        "Новые",
        "Q1",
        "Q2",
        "Q3",
        "Q4",
        "Выбыли",
    ]
    links = set(zip(sk.link.source, sk.link.target, sk.link.value, strict=True))
    assert (0, 6, 1) in links  # A: Q1(left) → Q2(right)
    assert (1, 5, 1) in links  # B: Q2(left) → Q1(right)


def test_transition_sankey_payloads_keys() -> None:
    # JS restyles the Sankey by reading exactly these keys; a rename would break
    # the live period switch while HTML substring tests stay green.
    holdings = {
        "2022-01": {"Q1": ["A"], "Q2": ["B"], "Q3": [], "Q4": []},
        "2022-02": {"Q1": ["B"], "Q2": ["A"], "Q3": [], "Q4": []},
    }
    payloads = transition_sankey_payloads(holdings)
    assert "all" in payloads
    assert set(payloads["all"]) == {"source", "target", "value", "color", "customdata", "title"}


def test_load_q_values_roundtrip(tmp_path: Path) -> None:
    df = _sample_q_values()
    path = tmp_path / "q_values.csv"
    _write_q_csv(path, df)
    loaded = load_q_values(path)
    pd.testing.assert_frame_equal(loaded, df, check_freq=False, check_names=False)


def test_dynamics_has_five_traces() -> None:
    fig = plot_q1_q4_dynamics(_sample_q_values())
    names = [t.name for t in fig.data]
    assert names == ["Q1", "Q2", "Q3", "Q4", "MCFTRR"]
    assert fig.layout.yaxis.type == "log"


def test_dynamics_starts_at_one() -> None:
    fig = plot_q1_q4_dynamics(_sample_q_values())
    for trace in fig.data:
        assert math.isclose(trace.y[0], 1.0, abs_tol=1e-9), f"{trace.name} should start at 1.0"


def _sample_long_q_values() -> pd.DataFrame:
    """13-year sample so all of 1y/3y/5y/10y/all windows fit."""
    months = pd.period_range("2013-01", "2026-01", freq="M")
    n = len(months)
    return pd.DataFrame(
        {
            "Q1": [1.0 * 1.012**i for i in range(n)],
            "Q2": [1.0 * 1.006**i for i in range(n)],
            "Q3": [1.0 * 1.000**i for i in range(n)],
            "Q4": [1.0 * 0.994**i for i in range(n)],
            "MCFTRR": [1.0 * 1.008**i for i in range(n)],
        },
        index=months,
    )


def test_dynamics_has_rangeslider_and_rebase_buttons() -> None:
    fig = plot_q1_q4_dynamics(_sample_long_q_values())
    # Rangeslider on every chart (not just dynamics).
    assert fig.layout.xaxis.rangeslider.visible is True
    assert fig.layout.xaxis.rangeslider.thickness >= 0.1
    # Rebase buttons live under layout.updatemenus.
    buttons = fig.layout.updatemenus[0].buttons
    labels = [b.label for b in buttons]
    assert labels == ["1y", "3y", "5y", "10y", "all"]
    # Default selection = "10y" when it fits — recent regime is more relevant
    # than 13y compressed onto one screen.
    assert fig.layout.updatemenus[0].active == labels.index("10y")


def test_rangeslider_on_chart_pages() -> None:
    """Rangeslider on the dynamics and alpha pages, not just dynamics."""
    for fig in [
        plot_q1_q4_dynamics(_sample_long_q_values()),
        plot_q1_minus_mcftrr(_sample_long_q_values()),
    ]:
        assert fig.layout.xaxis.rangeslider.visible is True


def test_rebase_button_5y_starts_at_one() -> None:
    """The 5y button's pre-computed view must start at NAV=1.0 for every trace."""
    fig = plot_q1_q4_dynamics(_sample_long_q_values())
    five_y = next(b for b in fig.layout.updatemenus[0].buttons if b.label == "5y")
    data_update = five_y.args[0]
    y_arrays = data_update["y"]
    for series in y_arrays:
        assert math.isclose(series[0], 1.0, abs_tol=1e-9)


def test_rebase_button_updates_title_subtitle() -> None:
    """Click on 5y must rewrite the title to show the rebased window's date range."""
    fig = plot_q1_q4_dynamics(_sample_long_q_values())
    five_y = next(b for b in fig.layout.updatemenus[0].buttons if b.label == "5y")
    layout_update = five_y.args[1]
    new_title = layout_update["title.text"]
    # Title still contains the chart name + a "60 months" 5-year subtitle.
    assert "Momentum Q1–Q4 dynamics vs MCFTRR" in new_title
    # 5y back from index end inclusive → 60+1 boundary months.
    assert "61 months" in new_title


def test_rebase_button_all_matches_full_series() -> None:
    """The 'all' button is just the original data; first NAV must be 1.0 too."""
    fig = plot_q1_q4_dynamics(_sample_long_q_values())
    all_btn = next(b for b in fig.layout.updatemenus[0].buttons if b.label == "all")
    y_arrays = all_btn.args[0]["y"]
    for series in y_arrays:
        assert math.isclose(series[0], 1.0, abs_tol=1e-9)


def test_rebase_skips_windows_that_dont_fit() -> None:
    """Sample is 12 months: 1y fits (12>=12), 3y/5y/10y don't."""
    short = _sample_q_values()  # 12 months
    fig = plot_q1_q4_dynamics(short)
    labels = [b.label for b in fig.layout.updatemenus[0].buttons]
    assert labels == ["1y", "all"]


def test_unit_baseline_present_on_all_charts() -> None:
    """Each chart has a y=1 reference line so the 'no growth' level is visible."""
    for fig in [
        plot_q1_q4_dynamics(_sample_q_values()),
        plot_q1_minus_mcftrr(_sample_q_values()),
    ]:
        hlines = [s for s in fig.layout.shapes if s.y0 == 1.0 and s.y1 == 1.0]
        assert hlines, "expected a horizontal reference line at y=1"


def test_title_contains_date_range_subtitle() -> None:
    fig = plot_q1_q4_dynamics(_sample_q_values())
    assert "12 months" in fig.layout.title.text
    assert "Jan 2022" in fig.layout.title.text


def test_hover_shows_month_year() -> None:
    """Hover header format must show e.g. 'Mar 2026', not full ISO date."""
    fig = plot_q1_q4_dynamics(_sample_q_values())
    assert fig.layout.xaxis.hoverformat == "%b %Y"


def test_mcftrr_is_dashed_others_solid() -> None:
    """MCFTRR is the benchmark — should be visually distinct from Q-lines."""
    fig = plot_q1_q4_dynamics(_sample_q_values())
    dashes = {t.name: t.line.dash for t in fig.data}
    assert dashes["MCFTRR"] == "dash"
    for q in ["Q1", "Q2", "Q3", "Q4"]:
        assert dashes[q] == "solid"


def _alpha_line(fig: Any) -> Any:
    return next(t for t in fig.data if t.name == "Q1/MCFTRR cumulative")


def test_alpha_line_is_ratio_q1_mcftrr() -> None:
    df = _sample_q_values()  # first ratio == 1.0 → rebase leaves the last point intact
    fig = plot_q1_minus_mcftrr(df)
    line = _alpha_line(fig)
    expected_last = df["Q1"].iloc[-1] / df["MCFTRR"].iloc[-1]
    assert math.isclose(line.y[-1], expected_last, rel_tol=1e-12)
    assert fig.layout.yaxis.type == "log"


def test_alpha_single_bar_layout() -> None:
    """One column per month: Q1 return (blue), the gap split into green-win and
    red-loss bars based at the MCFTRR level, and MCFTRR drawn as a tick."""
    df = _sample_long_q_values()  # Q1 outgrows MCFTRR every month → all wins
    fig = plot_q1_minus_mcftrr(df)
    bars = [t for t in fig.data if t.type == "bar"]
    assert [b.name for b in bars] == ["Q1 return", "Q1 > MCFTRR", "Q1 < MCFTRR"]
    for bar in bars:
        assert bar.yaxis == "y2"  # raw monthly returns, not rebased
    q1_bar, win_bar, loss_bar = bars
    q1_r = df["Q1"].iloc[-1] / df["Q1"].iloc[-2] - 1
    m_r = df["MCFTRR"].iloc[-1] / df["MCFTRR"].iloc[-2] - 1
    assert math.isclose(q1_bar.y[-1], q1_r, rel_tol=1e-12)
    assert math.isclose(win_bar.y[-1], q1_r - m_r, rel_tol=1e-9)
    assert math.isclose(win_bar.base[-1], m_r, rel_tol=1e-9)
    assert win_bar.marker.color == "#2ca02c"
    assert loss_bar.marker.color == "#d62728"
    # Hover the gap (customdata), not the based bar's top (which equals Q1).
    assert "customdata" in win_bar.hovertemplate
    assert math.isclose(win_bar.customdata[-1][0], q1_r - m_r, rel_tol=1e-9)
    mcftrr = next(t for t in fig.data if t.name == "MCFTRR return")
    assert mcftrr.type == "scatter" and mcftrr.yaxis == "y2"


def test_alpha_gap_split_by_sign() -> None:
    """Win months populate the green trace, loss months the red trace."""
    months = pd.period_range("2022-01", "2022-04", freq="M")
    df = pd.DataFrame(
        {
            "Q1": [1.0, 1.05, 1.0395, 1.04],  # +5%, then −1%
            "Q2": [1.0] * 4,
            "Q3": [1.0] * 4,
            "Q4": [1.0] * 4,
            "MCFTRR": [1.0, 1.01, 1.0201, 1.030301],  # +1% each month
        },
        index=months,
    )
    fig = plot_q1_minus_mcftrr(df)
    win = next(t for t in fig.data if t.name == "Q1 > MCFTRR")
    loss = next(t for t in fig.data if t.name == "Q1 < MCFTRR")
    # i=1: Q1 +5% > +1% → win populated, loss empty.
    assert not math.isnan(win.y[1]) and math.isnan(loss.y[1])
    # i=2: Q1 −1% < +1% → loss populated, win empty.
    assert math.isnan(win.y[2]) and not math.isnan(loss.y[2])


def test_alpha_secondary_axis_is_percent_and_overlay() -> None:
    fig = plot_q1_minus_mcftrr(_sample_long_q_values())
    assert fig.layout.barmode == "overlay"
    assert fig.layout.yaxis2.overlaying == "y"
    assert fig.layout.yaxis2.side == "right"
    assert fig.layout.yaxis2.tickformat == ".0%"


def test_alpha_rangeslider_matches_window_not_full_bars() -> None:
    """Regression: full-range bars must not stretch the slider past the windowed
    line and leave a grey unselected band on the left."""
    fig = plot_q1_minus_mcftrr(_sample_long_q_values())
    xr = fig.layout.xaxis.range
    sr = fig.layout.xaxis.rangeslider.range
    assert xr is not None and sr is not None
    assert list(sr) == list(xr)


def test_alpha_rebase_buttons_touch_only_the_line() -> None:
    """Window buttons must restyle the line trace alone — else they broadcast the
    rebased ratio onto the return bars."""
    fig = plot_q1_minus_mcftrr(_sample_long_q_values())
    line_idx = next(i for i, t in enumerate(fig.data) if t.name == "Q1/MCFTRR cumulative")
    for btn in fig.layout.updatemenus[0].buttons:
        assert list(btn.args[2]) == [line_idx]


def test_x_axis_uses_datetime_not_strings() -> None:
    fig = plot_q1_q4_dynamics(_sample_q_values())
    for trace in fig.data:
        assert all(isinstance(x, dt.datetime) for x in trace.x)


def test_committed_bundle_matches_pinned_sha256() -> None:
    """The bundle at docs/pages/plotly.min.js must match the SHA pinned in
    site_builder.py. If you bump plotly Python and rebuild the bundle, update both."""
    bundle = Path(__file__).resolve().parent.parent / "docs" / "pages" / "plotly.min.js"
    assert bundle.exists(), f"{bundle} is missing. Run scripts/build_plotly_bundle/build.sh."
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    assert digest == PLOTLY_BUNDLE_SHA256, (
        f"bundle SHA256 mismatch — committed={digest!r}, "
        f"expected={PLOTLY_BUNDLE_SHA256!r}. Rebuild and update site_builder.py."
    )


def test_committed_bundle_size_is_custom_not_full() -> None:
    """Custom bundle is ~1.2MB (scatter+bar+sankey); full plotly is 4.7MB.
    Guard against accidentally committing the full bundle."""
    bundle = Path(__file__).resolve().parent.parent / "docs" / "pages" / "plotly.min.js"
    size = bundle.stat().st_size
    assert 500_000 < size < 2_000_000, (
        f"plotly.min.js is {size} bytes — expected ~1.2MB custom bundle. "
        "Did the full 4.7MB bundle get committed by accident?"
    )


def test_dynamics_uses_distinct_colors_per_trace() -> None:
    fig = plot_q1_q4_dynamics(_sample_q_values())
    colors = {t.name: t.line.color for t in fig.data}
    assert len(set(colors.values())) == 5


def test_hovertemplate_present_on_traces() -> None:
    fig = plot_q1_q4_dynamics(_sample_q_values())
    for trace in fig.data:
        assert trace.hovertemplate is not None
        assert "<extra></extra>" in trace.hovertemplate
