"""Static-site builder for GitHub Pages.

Reads backtest outputs + tickers dict, renders the HTML pages (index, the
chart pages, quartile transitions, q_history, methodology, and the optional
experiments page) plus a data.json with per-month Q-составы. Bundles a single
shared plotly.min.js next to the HTML.

Used by `momentum site build`. CI runs the same code path.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import shutil
from pathlib import Path
from typing import Any

from jinja2 import Environment, PackageLoader, select_autoescape
from markdown_it import MarkdownIt

from momentum.transitions import Q_LABELS, sticky_tickers, transition_windows
from tickers import load as load_tickers
from viz.plotly_charts import (
    _COLORS,
    _transition_subtitle,
    load_q_values,
    plot_q1_minus_mcftrr,
    plot_q1_q4_dynamics,
    plot_quartile_transitions,
    plot_registry_figure,
    transition_sankey_payloads,
)
from viz.series_registry import q1_signals, weight_sweep

# Custom-bundled plotly.min.js (scatter+bar+sankey only). Pinned by SHA so a
# silent swap to the 4.7 MB full bundle is caught in tests.
PLOTLY_BUNDLE_SHA256 = "54db33f426b36f8ffa0193c423de08056c4a9702f70214d3fac392b320ce9c3d"
PLOTLY_BUNDLE_FILENAME = "plotly.min.js"

NAV_LINKS: list[tuple[str, str]] = [
    ("Home", "index.html"),
    ("Q1–Q4 dynamics", "q1_q4_dynamics.html"),
    ("Q1 vs MCFTRR alpha", "q1_minus_mcftrr.html"),
    ("Quartile composition", "q_history.html"),
    ("Quartile flows", "transitions.html"),
    ("Methodology", "methodology.html"),
    ("Experiments", "compare.html"),
]


def _env() -> Environment:
    return Environment(
        loader=PackageLoader("viz", "templates"),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _chart_embed(fig: Any, *, div_id: str) -> str:
    # include_plotlyjs=False → reuse the shared <script src="plotly.min.js">
    # already loaded in base.html <head>.
    # div_id is pinned so rebuilds are byte-identical (plotly otherwise assigns
    # a random UUID per div).
    html: str = fig.to_html(
        include_plotlyjs=False,
        full_html=False,
        default_height="78vh",
        default_width="100%",
        div_id=div_id,
        config={"responsive": True, "displaylogo": False},
    )
    return html


def _load_holdings(holdings_dir: Path) -> dict[str, dict[str, list[str]]]:
    """Read holdings/YYYY-MM.json into {month: {Q1: [...], ...}}."""
    out: dict[str, dict[str, list[str]]] = {}
    for f in sorted(holdings_dir.glob("*.json")):
        month = f.stem
        out[month] = json.loads(f.read_text(encoding="utf-8"))
    return out


def _short_month(month: str) -> str:
    """YYYY-MM → MM.YY (e.g. 2020-04 → 04.20)."""
    return f"{month[5:7]}.{month[2:4]}"


def _sticky_cards(
    holdings: dict[str, dict[str, list[str]]], tickers: dict[str, Any]
) -> list[dict[str, Any]]:
    """Top-10 longest-tenure tickers per quartile, shaped for transitions.html."""
    by_q = sticky_tickers(holdings, top_n=10)
    return [
        {
            "q": q,
            "color": _COLORS[q],
            "rows": [
                {
                    "ticker": r.ticker,
                    "canonical": _canonical(tickers, r.ticker),
                    "length": r.length,
                    # End month only; start is implied by the "Мес" length column.
                    "until": _short_month(r.end),
                }
                for r in by_q[q]
            ],
        }
        for q in Q_LABELS
    ]


def _sticky_sets(
    holdings: dict[str, dict[str, list[str]]], tickers: dict[str, Any]
) -> list[dict[str, Any]]:
    """Sticky cards per period window, so one selector filters the top-10 too."""
    months = sorted(holdings)
    return [
        {
            "window": label,
            "period": _transition_subtitle(wm),
            "cards": _sticky_cards({m: holdings[m] for m in wm}, tickers),
        }
        for label, wm in transition_windows(months)
    ]


def _canonical(tickers: dict[str, Any], ticker: str) -> str:
    entry = tickers.get(ticker)
    if entry is None:
        return ""
    return str(entry.get("canonical") or "")


def _load_pending(path: Path | None) -> dict[str, list[dict[str, Any]]]:
    """Read pending.json {month: [entry, ...]} (task 008). Missing → empty."""
    if path is None or not path.exists():
        return {}
    obj: dict[str, list[dict[str, Any]]] = json.loads(path.read_text(encoding="utf-8"))
    return obj


def _load_universe_meta(path: Path | None) -> dict[str, dict[str, Any]]:
    """Read universe_meta.csv → {month: {cut_rub, marginal, n}}. Missing → empty."""
    if path is None or not path.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            cut_raw = (row.get("cut_rub") or "").strip()
            out[row["month"]] = {
                "cut_rub": int(cut_raw) if cut_raw else None,
                "marginal": row.get("marginal") or None,
                "n": int(row["n"]) if (row.get("n") or "").strip() else None,
            }
    return out


def _build_data_json(
    holdings: dict[str, dict[str, list[str]]],
    tickers: dict[str, Any],
    pending: dict[str, list[dict[str, Any]]],
    universe_meta: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Embed canonical names inline so q_history.html needs no extra fetch."""
    months = sorted(holdings)
    out_holdings: dict[str, dict[str, list[list[str]]]] = {}
    for m in months:
        per_q: dict[str, list[list[str]]] = {}
        for q in ("Q1", "Q2", "Q3", "Q4"):
            per_q[q] = [[t, _canonical(tickers, t)] for t in holdings[m].get(q, [])]
        out_holdings[m] = per_q

    out_pending: dict[str, list[dict[str, Any]]] = {}
    for m, entries in pending.items():
        out_pending[m] = [{**e, "canonical": _canonical(tickers, e["ticker"])} for e in entries]

    return {
        "months": months,
        "holdings": out_holdings,
        "pending": out_pending,
        "universe_meta": universe_meta,
    }


def _copy_bundle(bundle_src: Path, out_dir: Path) -> None:
    dest = out_dir / PLOTLY_BUNDLE_FILENAME
    if dest.resolve() == bundle_src.resolve():
        return
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(bundle_src, dest)


def _render_methodology_md(md_path: Path) -> str:
    md = MarkdownIt("commonmark", {"html": False}).enable("table")
    rendered: str = md.render(md_path.read_text(encoding="utf-8"))
    return rendered


def build_site(
    *,
    q_values_path: Path,
    holdings_dir: Path,
    tickers_path: Path,
    methodology_md: Path,
    bundle_src: Path,
    out_dir: Path,
    signal: str,
    compare_simple_path: Path | None = None,
    compare_curve_fit_path: Path | None = None,
    compare_sweep_path: Path | None = None,
    pending_path: Path | None = None,
    universe_meta_path: Path | None = None,
) -> dict[str, Path]:
    """Render the full site to `out_dir`. Returns map of logical name → path.

    `compare_*_path` are signal-independent sources for the explorer page
    (task 20): when all three exist, compare.html is rendered. The per-signal
    pages above stay tied to `signal`."""
    env = _env()
    q_values = load_q_values(q_values_path)
    holdings = _load_holdings(holdings_dir)
    tickers = load_tickers(tickers_path)

    fig_dyn = plot_q1_q4_dynamics(q_values)
    fig_alpha = plot_q1_minus_mcftrr(q_values)
    fig_transitions = plot_quartile_transitions(holdings)

    # Distinct div_ids: same fig may appear standalone (full-page) and embedded
    # (on index). Each render gets its own stable id.
    embed_dyn_solo = _chart_embed(fig_dyn, div_id="chart-dyn")
    embed_alpha_solo = _chart_embed(fig_alpha, div_id="chart-alpha")
    embed_transitions = _chart_embed(fig_transitions, div_id="chart-transitions")
    embed_dyn_idx = _chart_embed(fig_dyn, div_id="chart-dyn-idx")
    embed_alpha_idx = _chart_embed(fig_alpha, div_id="chart-alpha-idx")

    first_month = str(q_values.index.min())
    last_month = str(q_values.index.max())
    build_iso = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC")

    pages: dict[str, Path] = {}

    def render(name: str, template: str, ctx: dict[str, Any]) -> None:
        full_ctx = {
            "nav_links": NAV_LINKS,
            "current_href": name,
            **ctx,
        }
        html = env.get_template(template).render(**full_ctx)
        path = out_dir / name
        _atomic_write(path, html)
        pages[name] = path

    render(
        "index.html",
        "index.html",
        {
            "title": "Home",
            "chart_dyn": embed_dyn_idx,
            "chart_alpha": embed_alpha_idx,
            "build_iso": build_iso,
            "first_month": first_month,
            "last_month": last_month,
        },
    )
    render(
        "q1_q4_dynamics.html",
        "chart.html",
        {"title": "Q1–Q4 dynamics", "chart_html": embed_dyn_solo},
    )
    render(
        "q1_minus_mcftrr.html",
        "chart.html",
        {"title": "Q1 vs MCFTRR alpha", "chart_html": embed_alpha_solo},
    )
    render(
        "transitions.html",
        "transitions.html",
        {
            "title": "Quartile flows",
            "chart_html": embed_transitions,
            "sticky_sets": _sticky_sets(holdings, tickers),
            "sankey_payloads": json.dumps(transition_sankey_payloads(holdings), ensure_ascii=False),
        },
    )
    render(
        "q_history.html",
        "q_history.html",
        {"title": "Quartile composition", "signal": signal},
    )
    render(
        "methodology.html",
        "methodology.html",
        {"title": "Methodology", "markdown_html": _render_methodology_md(methodology_md)},
    )

    if compare_simple_path and compare_curve_fit_path and compare_sweep_path:
        headline = q1_signals(
            simple_path=compare_simple_path, curve_fit_path=compare_curve_fit_path
        )
        sweep = weight_sweep(sweep_path=compare_sweep_path)
        fig_headline = plot_registry_figure(headline, title="Strategy comparison")
        fig_sweep = plot_registry_figure(
            sweep,
            title="The momentum effect holds for any weighting",
            gradient=True,
            formula="score = (a·r(12-1) + (1−a)·r(6-1)) / σ(12),  a = 1.0 … 0.0",
        )
        render(
            "compare.html",
            "compare.html",
            {
                "title": "Experiments",
                "chart_headline": _chart_embed(fig_headline, div_id="chart-compare-headline"),
                "chart_sweep": _chart_embed(fig_sweep, div_id="chart-compare-sweep"),
            },
        )

    data_json = _build_data_json(
        holdings,
        tickers,
        _load_pending(pending_path),
        _load_universe_meta(universe_meta_path),
    )
    data_path = out_dir / "data.json"
    _atomic_write(
        data_path,
        json.dumps(data_json, ensure_ascii=False, separators=(",", ":")),
    )
    pages["data.json"] = data_path

    _copy_bundle(bundle_src, out_dir)
    pages[PLOTLY_BUNDLE_FILENAME] = out_dir / PLOTLY_BUNDLE_FILENAME

    return pages


def default_bundle_path() -> Path:
    """Project-tree default for plotly.min.js. Used by the CLI and tests."""
    # site_builder.py lives at src/viz/site_builder.py → repo root is 2 parents up.
    return Path(__file__).resolve().parents[2] / "docs" / "pages" / PLOTLY_BUNDLE_FILENAME


def default_methodology_path() -> Path:
    return Path(__file__).resolve().parents[2] / "docs" / "methodology.md"


__all__ = [
    "NAV_LINKS",
    "PLOTLY_BUNDLE_FILENAME",
    "PLOTLY_BUNDLE_SHA256",
    "build_site",
    "default_bundle_path",
    "default_methodology_path",
]
