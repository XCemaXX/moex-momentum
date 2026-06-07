"""Plotly figure for the mages-index page (task 002, phase 1).

Reuses the shared NAV-chart helpers from plotly_charts (log y, rebase buttons,
unit baseline) so it matches the rest of the site. Input is the two-column
frame from mages.curve.build_mages_frame (Mages, MCFTRR), indexed Period[M].
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from viz.plotly_charts import (
    _COLORS,
    _add_unit_baseline,
    _apply_default_view,
    _base_layout,
    _gradient_color,
    _rebase_buttons,
    _subtitle_for,
    _trace,
    _x_dates,
)

_MAGES_COLOR = "#1f77b4"
# Equal-weight Q1 drawn neutral so the λ fan (blue→orange) reads as the tilt.
_Q1_BASE_COLOR = "#333333"


def plot_mages_vs_mcftrr(frame: pd.DataFrame) -> go.Figure:
    """Mages index NAV vs MCFTRR, log y. MCFTRR dashed (benchmark, not a
    strategy). Window buttons rebase the start of the window to NAV = 1.0.

    With under 3 years of mages history only 1y/all buttons appear; 3y/5y show
    up automatically as the series grows past those spans."""
    cols = ["Mages", "MCFTRR"]
    x = _x_dates(frame.index)
    fig = go.Figure()
    fig.add_trace(_trace("Mages index", x, frame["Mages"].tolist(), color=_MAGES_COLOR))
    mcftrr = frame["MCFTRR"].tolist()
    fig.add_trace(_trace("MCFTRR", x, mcftrr, color=_COLORS["MCFTRR"], dash="dash"))
    title = "Mages index vs MCFTRR"
    buttons = _rebase_buttons(frame, cols, title=title)
    fig.update_layout(**_base_layout(title, _subtitle_for(frame), rebase_buttons=buttons))
    _add_unit_baseline(fig)
    _apply_default_view(fig, buttons)
    return fig


_REF_STYLE = {
    "Mages": ("Mages index", _MAGES_COLOR),
    "MCFTRR": ("MCFTRR", _COLORS["MCFTRR"]),
}


def plot_weighted_q1(frame: pd.DataFrame) -> go.Figure:
    """Mages-tilted Q1 (λ fan) vs equal-weight Q1, log y. λ=0 is the equal Q1
    (neutral colour); the λ fan ramps blue→orange with tilt strength. Mages index
    and MCFTRR are dashed reference lines, not Q1 variants."""
    refs = [c for c in ("Mages", "MCFTRR") if c in frame.columns]
    strat = [c for c in frame.columns if c not in refs]
    cols = [*strat, *refs]
    x = _x_dates(frame.index)
    fig = go.Figure()
    n = max(len(strat) - 1, 1)
    for i, c in enumerate(strat):
        color = _Q1_BASE_COLOR if c == "Q1 (equal)" else _gradient_color(i / n)
        fig.add_trace(_trace(c, x, frame[c].tolist(), color=color))
    for c in refs:
        label, color = _REF_STYLE[c]
        fig.add_trace(_trace(label, x, frame[c].tolist(), color=color, dash="dash"))
    title = "Mages-weighted Q1 vs equal-weight Q1"
    buttons = _rebase_buttons(frame, cols, title=title)
    fig.update_layout(**_base_layout(title, _subtitle_for(frame), rebase_buttons=buttons))
    _add_unit_baseline(fig)
    _apply_default_view(fig, buttons)
    return fig
