"""Plotly figure builders for backtest results.

Charts share a log y-axis and start from NAV = 1 at the first month. The alpha
chart adds a secondary linear % axis for monthly Q1/MCFTRR return bars.
Input is the wide `q_values.csv` table loaded into a DataFrame indexed by
`Period[M]` with columns Q1..Q4, MCFTRR.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd
import plotly.graph_objects as go

from momentum.transitions import (
    DROPPED,
    NEW,
    Q_LABELS,
    transition_flows,
    transition_windows,
)
from storage.records import read_records
from storage.schemas import Q_VALUES_CASTS

if TYPE_CHECKING:
    from viz.series_registry import Series

# Colours mirror the author's reference charts.
_COLORS = {
    "Q1": "#1f77b4",
    "Q2": "#2ca02c",
    "Q3": "#ff7f0e",
    "Q4": "#9467bd",
    "MCFTRR": "#d62728",
}

# Q1 top15 concentration line (task 026): cyan — distinct from Q1 blue and the
# red MCFTRR benchmark on the dynamics chart.
Q1_TOP15_COLOR = "#17becf"

# The alpha line is neither a Q-series nor the benchmark — give it a neutral
# colour so the monthly return bars read clearly underneath.
_ALPHA_LINE_COLOR = "#333333"
# Monthly Q1-vs-index bars: Q1 column blue, the signed gap green (Q1 won) /
# red (lost), MCFTRR tick orange — orange (not the usual red) so it never
# clashes with the red "loss" fill.
_GAP_WIN = "#2ca02c"
_GAP_LOSS = "#d62728"
_MCFTRR_TICK_COLOR = "#ff7f0e"


def load_q_values(path: Path) -> pd.DataFrame:
    """Load q_values.csv into a DataFrame indexed by Period[M]."""
    rows = read_records(path, casts=Q_VALUES_CASTS)
    df = pd.DataFrame(rows)
    df["month"] = pd.PeriodIndex(df["month"], freq="M")
    df = df.set_index("month").sort_index()
    return df[["Q1", "Q2", "Q3", "Q4", "MCFTRR"]].astype(float)


def _x_dates(index: pd.Index) -> list[dt.datetime]:
    # Plotly accepts datetime objects directly — keeps range selector etc. working.
    # normalize() drops the 23:59:59.999 of how="end": that boundary rounds up to
    # the next month in Plotly's month hover (May point showing as "Jun").
    period_index = pd.PeriodIndex(index, freq="M")
    return [p.to_timestamp(how="end").normalize().to_pydatetime() for p in period_index]


_REBASE_WINDOWS_YEARS: tuple[int | None, ...] = (1, 3, 5, 10, None)

# Window the chart opens with. The user usually cares about recent regime, not
# 13 years of history compressed into one screen. Falls back to "all" if the
# dataset is shorter than this window.
_DEFAULT_REBASE_LABEL = "10y"


def _title_text(title: str, subtitle: str) -> str:
    return f'<b>{title}</b><br><span style="font-size:13px;color:#666">{subtitle}</span>'


def _registry_title_text(title: str, subtitle: str, *, formula: str | None) -> str:
    """Title block for registry figures: bold title, optional formula line (so an
    exported PNG is self-explanatory), then the date-range subtitle."""
    head = f"<b>{title}</b>"
    if formula:
        head += f'<br><span style="font-size:13px;color:#444">{formula}</span>'
    return f'{head}<br><span style="font-size:12px;color:#888">{subtitle}</span>'


def _subtitle_for(window: pd.DataFrame) -> str:
    first, last = window.index.min(), window.index.max()
    return f"{first.strftime('%b %Y')} — {last.strftime('%b %Y')}, {len(window)} months"


def _rebase_buttons(
    q_values: pd.DataFrame,
    columns: list[str],
    *,
    title: str,
    trace_indices: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Pre-compute views for the rebase-on-click buttons.

    For each window, the visible series are re-normalised so that the value at
    the first month of the window equals 1.0, the x-axis is zoomed to the
    window, and the chart subtitle is rewritten to reflect the new range.

    `trace_indices` restricts the restyle to those figure traces, so a chart
    with extra non-rebased traces (e.g. monthly-return bars) leaves them
    untouched on click. None (default) rebases all traces positionally.
    """
    last = q_values.index.max()
    buttons: list[dict[str, Any]] = []
    for years in _REBASE_WINDOWS_YEARS:
        if years is None:
            label = "all"
            window = q_values
        else:
            # Only show this button if the dataset actually spans the window —
            # otherwise "10y" on 5y of data is misleading.
            if len(q_values) < years * 12:
                continue
            cutoff = last - years * 12
            window = q_values[q_values.index >= cutoff]
            label = f"{years}y"
        rebased = window[columns] / window[columns].iloc[0]
        dates = _x_dates(rebased.index)
        y_arrays = [rebased[c].tolist() for c in columns]
        x_arrays = [dates] * len(columns)
        args: list[Any] = [
            {"x": x_arrays, "y": y_arrays},
            {
                "xaxis.range": [dates[0], dates[-1]],
                # Pin the slider to the window too: full-range traces left
                # untouched by this restyle (e.g. monthly bars) must not stretch
                # the slider past the window and leave a grey unselected band.
                "xaxis.rangeslider.range": [dates[0], dates[-1]],
                "title.text": _title_text(title, _subtitle_for(window)),
            },
        ]
        if trace_indices is not None:
            args.append(trace_indices)
        buttons.append({"label": label, "method": "update", "args": args})
    return buttons


def _base_layout(
    title: str,
    subtitle: str,
    *,
    rebase_buttons: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    layout: dict[str, Any] = {
        "title": {
            "text": _title_text(title, subtitle),
            "x": 0.02,
            "xanchor": "left",
            "font": {"size": 18},
        },
        "xaxis": {
            "title": None,
            "showgrid": True,
            "tickformat": "%Y",
            # Hover header shows e.g. "Mar 2026" — month + year, no day.
            "hoverformat": "%b %Y",
            # Rangeslider on every chart — same scrub UX across pages.
            "rangeslider": {"visible": True, "thickness": 0.12},
        },
        "yaxis": {"title": "NAV (start = 1)", "type": "log", "showgrid": True},
        "hovermode": "x unified",
        "template": "plotly_white",
        # Legend above plot, below the rebase buttons. Previously sat at y=-0.12,
        # which overlapped the rangeslider's preview traces and was unreadable.
        "legend": {
            "orientation": "h",
            "y": 1.02,
            "x": 0,
            "xanchor": "left",
            "yanchor": "bottom",
        },
        # Top margin holds title (top-left), rebase buttons (top-right),
        # and legend (between title and plot).
        "margin": {"l": 60, "r": 30, "t": 130, "b": 60},
    }
    if rebase_buttons:
        layout["updatemenus"] = [
            {
                "type": "buttons",
                "direction": "right",
                "buttons": rebase_buttons,
                "active": _default_button_index(rebase_buttons),
                "x": 1.0,
                "y": 1.10,
                "xanchor": "right",
                "yanchor": "bottom",
                "showactive": True,
                "bgcolor": "#f4f4f4",
                "pad": {"l": 4, "r": 4, "t": 2, "b": 2},
            }
        ]
    return layout


def _default_button_index(buttons: list[dict[str, Any]]) -> int:
    labels = [b["label"] for b in buttons]
    if _DEFAULT_REBASE_LABEL in labels:
        return labels.index(_DEFAULT_REBASE_LABEL)
    return labels.index("all")


def _apply_default_view(
    fig: go.Figure,
    buttons: list[dict[str, Any]],
    trace_indices: list[int] | None = None,
) -> None:
    """Overwrite initial figure data + xaxis range + title with the default
    rebase window's view. Keeps the chart consistent with the highlighted button.

    `trace_indices` maps the button's data arrays onto those figure traces (must
    match what was passed to `_rebase_buttons`); None maps them positionally."""
    btn = buttons[_default_button_index(buttons)]
    data_update = btn["args"][0]
    layout_update = btn["args"][1]
    targets = trace_indices if trace_indices is not None else list(range(len(data_update["x"])))
    for idx, xs, ys in zip(targets, data_update["x"], data_update["y"], strict=True):
        fig.data[idx].x = xs
        fig.data[idx].y = ys
    window_range = layout_update["xaxis.range"]
    fig.update_layout(
        {
            "xaxis": {"range": window_range, "rangeslider": {"range": window_range}},
            "title": {"text": layout_update["title.text"]},
        }
    )


def _trace(
    name: str,
    x: list[dt.datetime],
    y: list[float],
    *,
    color: str,
    dash: str = "solid",
) -> go.Scatter:
    return go.Scatter(
        x=x,
        y=y,
        mode="lines",
        name=name,
        line={"color": color, "width": 2, "dash": dash},
        hovertemplate=f"{name}: %{{y:.2f}}<extra></extra>",
    )


def _add_unit_baseline(fig: go.Figure) -> None:
    # Reference line at NAV = 1 anchors the eye to the "no growth" level.
    fig.add_hline(y=1.0, line_dash="dot", line_color="#999", line_width=1)


def plot_q1_q4_dynamics(
    q_values: pd.DataFrame,
    *,
    extra_series: list[tuple[str, pd.Series, str]] | None = None,
) -> go.Figure:
    """5 NAV lines (Q1..Q4 + MCFTRR), log y, plus any `extra_series`.
    MCFTRR is drawn dashed to mark it as the benchmark, not a strategy line.
    `extra_series` is (label, NAV series, colour) overlaid as extra solid
    strategy lines (task 026: Q1 top15). Each must be indexed like q_values.
    Buttons 1y/3y/5y/10y/all rebase the start of the window to NAV=1.0."""
    extra_series = extra_series or []
    frame = q_values.copy()
    for label, series, _ in extra_series:
        frame[label] = series
    cols = ["Q1", "Q2", "Q3", "Q4", "MCFTRR", *(label for label, _, _ in extra_series)]
    colors = {**_COLORS, **{label: color for label, _, color in extra_series}}
    x = _x_dates(frame.index)
    fig = go.Figure()
    for col in cols:
        dash = "dash" if col == "MCFTRR" else "solid"
        fig.add_trace(_trace(col, x, frame[col].tolist(), color=colors[col], dash=dash))
    title = "Momentum Q1–Q4 dynamics vs MCFTRR"
    buttons = _rebase_buttons(frame, cols, title=title)
    fig.update_layout(**_base_layout(title, _subtitle_for(frame), rebase_buttons=buttons))
    _add_unit_baseline(fig)
    _apply_default_view(fig, buttons)
    return fig


def _spread_frame(
    q_values: pd.DataFrame, numerator: str, denominator: str, name: str
) -> pd.DataFrame:
    """A 1-column dataframe matching the q_values shape, holding the spread series."""
    return pd.DataFrame({name: q_values[numerator] / q_values[denominator]}, index=q_values.index)


def plot_q1_minus_mcftrr(q_values: pd.DataFrame) -> go.Figure:
    """Q1 vs MCFTRR, two ways. Left log axis: cumulative Q1 / MCFTRR ratio.
    Right % axis: one bar per month — blue column = Q1 return, orange tick =
    MCFTRR return, and the band between them filled green when Q1 beat the index
    that month, red when it lagged.

    Window buttons rebase only the line; the monthly bars are window-invariant."""
    return _plot_strategy_vs_mcftrr(q_values, "Q1", strat_name="Q1", title="Q1 vs MCFTRR alpha")


def _plot_strategy_vs_mcftrr(
    frame: pd.DataFrame,
    strat_col: str,
    *,
    strat_name: str,
    title: str,
    strat_color: str = _COLORS["Q1"],
) -> go.Figure:
    """Cumulative strategy/MCFTRR ratio + monthly return bars. `frame` carries
    the strategy NAV in `strat_col` and a MCFTRR column; `strat_name` labels the
    traces and `strat_color` paints the return column. Q1 is one caller (task 026
    adds Q1 top15, coloured to match its line on the dynamics chart)."""
    name = f"{strat_name}/MCFTRR cumulative"
    spread = _spread_frame(frame, strat_col, "MCFTRR", name)
    x = _x_dates(frame.index)

    strat_ret = frame[strat_col].pct_change()
    mcftrr_ret = frame["MCFTRR"].pct_change()
    gap = strat_ret - mcftrr_ret
    # Split the gap into two single-colour traces (win / loss) so the legend
    # shows a green square and a red square, not one ambiguous swatch. Each month
    # populates only one; NaN (incl. the first month) renders nothing.
    gap_win = [g if (pd.notna(g) and g >= 0) else float("nan") for g in gap]
    gap_loss = [g if (pd.notna(g) and g < 0) else float("nan") for g in gap]
    base = mcftrr_ret.tolist()
    # 2D customdata so %{customdata[0]} resolves the gap in the hover (see below).
    cd_win = [[g] for g in gap_win]
    cd_loss = [[g] for g in gap_loss]

    fig = go.Figure()
    # Strategy column (anchored at zero) first; the signed gap band overlays its top.
    fig.add_trace(
        go.Bar(
            x=x,
            y=strat_ret.tolist(),
            name=f"{strat_name} return",
            marker_color=strat_color,
            opacity=0.5,
            yaxis="y2",
            hovertemplate=f"{strat_name}: %{{y:+.1%}}<extra></extra>",
        )
    )
    # With `base` set, %{y} resolves to the bar's top (base+height = strat return),
    # so carry the gap itself in customdata to hover the difference, not the strat.
    fig.add_trace(
        go.Bar(
            x=x,
            y=gap_win,
            base=base,
            name=f"{strat_name} > MCFTRR",
            marker_color=_GAP_WIN,
            opacity=0.85,
            yaxis="y2",
            customdata=cd_win,
            hovertemplate=f"{strat_name}−MCFTRR: %{{customdata[0]:+.1%}}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            x=x,
            y=gap_loss,
            base=base,
            name=f"{strat_name} < MCFTRR",
            marker_color=_GAP_LOSS,
            opacity=0.85,
            yaxis="y2",
            customdata=cd_loss,
            hovertemplate=f"{strat_name}−MCFTRR: %{{customdata[0]:+.1%}}<extra></extra>",
        )
    )
    # MCFTRR as a level tick across each bar, not a second column.
    fig.add_trace(
        go.Scatter(
            x=x,
            y=mcftrr_ret.tolist(),
            name="MCFTRR return",
            mode="markers",
            marker={
                "symbol": "line-ew",
                "size": 9,
                "line": {"width": 2, "color": _MCFTRR_TICK_COLOR},
            },
            yaxis="y2",
            hovertemplate="MCFTRR: %{y:+.1%}<extra></extra>",
        )
    )
    line_idx = len(fig.data)
    fig.add_trace(_trace(name, x, spread[name].tolist(), color=_ALPHA_LINE_COLOR))

    buttons = _rebase_buttons(spread, [name], title=title, trace_indices=[line_idx])
    layout = _base_layout(title, _subtitle_for(spread), rebase_buttons=buttons)
    layout["barmode"] = "overlay"
    layout["yaxis2"] = {
        "title": "monthly return",
        "overlaying": "y",
        "side": "right",
        "tickformat": ".0%",
        "zeroline": True,
        "zerolinecolor": "#ccc",
        "showgrid": False,
    }
    fig.update_layout(**layout)
    _add_unit_baseline(fig)
    _apply_default_view(fig, buttons, trace_indices=[line_idx])
    return fig


# --- registry-driven multi-series figure (compare.html, task 20) -------------
#
# Separate from the per-page builders above: it takes a list of named Series
# (own colours, dashes, default visibility) and is ragged-safe on rebase, so
# series with different start months render correctly. Existing pages keep
# their exact output.

_BENCHMARK_COLOR = _COLORS["MCFTRR"]
_PALETTE = ["#1f77b4", "#2ca02c", "#9467bd", "#8c564b", "#e377c2"]


def _gradient_color(t: float) -> str:
    """Blue (#1f77b4, t=0) → orange (#ff7f0e, t=1). Avoids the red benchmark."""
    c0, c1 = (31, 119, 180), (255, 127, 14)
    rgb = tuple(round(c0[i] + (c1[i] - c0[i]) * t) for i in range(3))
    return f"rgb({rgb[0]},{rgb[1]},{rgb[2]})"


def _registry_rebase_buttons(
    frame: pd.DataFrame, columns: list[str], *, title: str, formula: str | None = None
) -> list[dict[str, Any]]:
    """Like `_rebase_buttons` but each column is normalised by its own first
    non-NaN value in the window — so ragged starts rebase to 1.0 at their own
    first month, not at a shared row that may be NaN for late-starting series."""
    last = frame.index.max()
    buttons: list[dict[str, Any]] = []
    for years in _REBASE_WINDOWS_YEARS:
        if years is None:
            label, window = "all", frame
        else:
            if len(frame) < years * 12:
                continue
            cutoff = last - years * 12
            window = frame[frame.index >= cutoff]
            label = f"{years}y"
        rebased = window[columns].copy()
        for c in columns:
            valid = rebased[c].dropna()
            if not valid.empty:
                rebased[c] = rebased[c] / valid.iloc[0]
        dates = _x_dates(rebased.index)
        buttons.append(
            {
                "label": label,
                "method": "update",
                "args": [
                    {"x": [dates] * len(columns), "y": [rebased[c].tolist() for c in columns]},
                    {
                        "xaxis.range": [dates[0], dates[-1]],
                        # Pin the slider to the window too, else it keeps the full
                        # range and leaves a grey unselected band under shorter views.
                        "xaxis.rangeslider.range": [dates[0], dates[-1]],
                        "title.text": _registry_title_text(
                            title, _subtitle_for(window), formula=formula
                        ),
                    },
                ],
            }
        )
    return buttons


def plot_registry_figure(
    series: list[Series], *, title: str, gradient: bool = False, formula: str | None = None
) -> go.Figure:
    """One Plotly figure from a list of Series. Strategies solid, benchmarks
    dashed; `gradient` colours strategies along a blue→orange ramp (sweep fan),
    otherwise cycles a categorical palette. `formula` prints under the title so
    an exported image is self-explanatory. Legend click hides/isolates; the
    rebase buttons (1y/3y/5y/10y/all) re-normalise the window to NAV=1.0."""
    frame = pd.DataFrame({s.id: s.nav for s in series}).sort_index()
    frame.index = pd.PeriodIndex(frame.index, freq="M")

    strategies = [s for s in series if s.kind == "strategy"]
    color: dict[str, str] = {}
    n = max(len(strategies) - 1, 1)
    for i, s in enumerate(strategies):
        color[s.id] = _gradient_color(i / n) if gradient else _PALETTE[i % len(_PALETTE)]
    for s in series:
        if s.kind == "benchmark":
            color[s.id] = _BENCHMARK_COLOR

    ids = [s.id for s in series]
    x = _x_dates(frame.index)
    fig = go.Figure()
    for s in series:
        dash = "dash" if s.kind == "benchmark" else "solid"
        fig.add_trace(
            go.Scatter(
                x=x,
                y=frame[s.id].tolist(),
                mode="lines",
                name=s.label,
                visible=True if s.default_visible else "legendonly",
                line={"color": color[s.id], "width": 2, "dash": dash},
                hovertemplate=f"{s.label}: %{{y:.2f}}<extra></extra>",
            )
        )
    buttons = _registry_rebase_buttons(frame, ids, title=title, formula=formula)
    fig.update_layout(**_base_layout(title, _subtitle_for(frame), rebase_buttons=buttons))
    # The formula line adds a row to the title block — reserve more top margin.
    top = 150 if formula else 100
    # Many series (the sweep fan) overflow the top horizontal legend and collide
    # with the title/rebase buttons — move them to a vertical legend on the right.
    if len(series) > 6:
        fig.update_layout(
            legend={"orientation": "v", "x": 1.01, "xanchor": "left", "y": 1.0, "yanchor": "top"},
            margin={"l": 60, "r": 190, "t": top, "b": 60},
        )
    elif formula:
        fig.update_layout(margin={"l": 60, "r": 30, "t": top, "b": 60})
    _add_unit_baseline(fig)
    _apply_default_view(fig, buttons)
    return fig


# --- quartile transitions (Sankey, task 001) ---------------------------------

_FLOW_NODE_GREY = "#b0b0b0"


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


_NODE_DISPLAY = [*Q_LABELS, "Новые", *Q_LABELS, "Выбыли"]


def _transition_subtitle(window_months: list[str]) -> str:
    if len(window_months) < 2:
        return "недостаточно истории"
    return f"{len(window_months)} месяцев · {window_months[0]} — {window_months[-1]}"


def _transition_node_index() -> tuple[dict[str, int], dict[str, int]]:
    left = [*Q_LABELS, NEW]
    right = [*Q_LABELS, DROPPED]
    left_idx = {label: i for i, label in enumerate(left)}
    right_idx = {label: i + len(left) for i, label in enumerate(right)}
    return left_idx, right_idx


def _sankey_links(
    holdings: dict[str, dict[str, list[str]]],
    left_idx: dict[str, int],
    right_idx: dict[str, int],
) -> tuple[list[int], list[int], list[int], list[str], list[float]]:
    """(source, target, value, colour, share) link arrays for one window.

    share = the link's fraction of its source node's total outflow — the
    transition probability shown in the hover next to the raw count.
    """
    flows = transition_flows(holdings)
    out_total: dict[str, int] = {}
    for (s_label, _d), n in flows.items():
        out_total[s_label] = out_total.get(s_label, 0) + n
    src: list[int] = []
    dst: list[int] = []
    val: list[int] = []
    colors: list[str] = []
    share: list[float] = []
    for (s_label, d_label), n in sorted(flows.items()):
        src.append(left_idx[s_label])
        dst.append(right_idx[d_label])
        val.append(n)
        base = _COLORS[s_label] if s_label in _COLORS else _FLOW_NODE_GREY
        colors.append(_rgba(base, 0.4))
        share.append(round(n / out_total[s_label], 4) if out_total[s_label] else 0.0)
    return src, dst, val, colors, share


def plot_quartile_transitions(holdings: dict[str, dict[str, list[str]]]) -> go.Figure:
    """Aggregate month-to-month quartile flow as a Sankey (the 'all' window).

    Left nodes are the source quartile (plus Новые = entered the universe), right
    nodes the next-month quartile (plus Выбыли = left it). The Qᵢ→Qᵢ diagonals are
    the stickiness mass. Links are coloured by source quartile; the hover shows
    the raw count and the link's share of that quartile's flow.

    The period selector lives in the page (HTML), driving this figure via
    `Plotly.restyle` with the arrays from `transition_sankey_payloads` — so one
    control filters both the Sankey and the sticky list.
    """
    left_idx, right_idx = _transition_node_index()
    node_colors = (
        [_COLORS[q] for q in Q_LABELS]
        + [_FLOW_NODE_GREY]
        + [_COLORS[q] for q in Q_LABELS]
        + [_FLOW_NODE_GREY]
    )
    months = sorted(holdings)
    src, dst, val, colors, share = _sankey_links(holdings, left_idx, right_idx)
    fig = go.Figure(
        go.Sankey(
            arrangement="snap",
            node={
                "label": _NODE_DISPLAY,
                "color": node_colors,
                "pad": 20,
                "thickness": 18,
                "line": {"color": "#888", "width": 0.5},
            },
            link={
                "source": src,
                "target": dst,
                "value": val,
                "color": colors,
                "customdata": share,
                "hovertemplate": "%{source.label} → %{target.label}<br>"
                "%{value} раз · %{customdata:.0%} перетока<extra></extra>",
            },
        )
    )
    fig.update_layout(
        title={
            "text": _title_text("Quartile flows", _transition_subtitle(months)),
            "x": 0.02,
            "xanchor": "left",
        },
        template="plotly_white",
        font={"size": 13},
        margin={"l": 20, "r": 20, "t": 90, "b": 20},
    )
    return fig


def transition_sankey_payloads(
    holdings: dict[str, dict[str, list[str]]],
) -> dict[str, dict[str, Any]]:
    """Per-window restyle payloads for the page's period buttons (JS-consumed).

    {label: {source, target, value, color, customdata, title}} — `title` is the
    full title HTML so the page can relayout it on switch."""
    left_idx, right_idx = _transition_node_index()
    months = sorted(holdings)
    out: dict[str, dict[str, Any]] = {}
    for label, wm in transition_windows(months):
        src, dst, val, colors, share = _sankey_links(
            {m: holdings[m] for m in wm}, left_idx, right_idx
        )
        out[label] = {
            "source": src,
            "target": dst,
            "value": val,
            "color": colors,
            "customdata": share,
            "title": _title_text("Quartile flows", _transition_subtitle(wm)),
        }
    return out
