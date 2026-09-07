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

import pandas as pd
from jinja2 import Environment, PackageLoader, select_autoescape
from markdown_it import MarkdownIt

from config import TOP_K_CONCENTRATION
from mages.curve import build_mages_frame
from mages.loader import load_quarters
from mages.weighted_q1 import build_mages_table, build_weighted_frame
from momentum.topn_fan import top_k_nav_from_scores
from momentum.transitions import Q_LABELS, sticky_tickers, transition_windows
from storage.records import write_text_atomic
from storage.schemas import SCORES_FIELDS
from tickers import load as load_tickers
from viz.mages_charts import plot_mages_vs_mcftrr, plot_weighted_q1
from viz.plotly_charts import (
    _COLORS,
    Q1_TOP15_COLOR,
    _plot_strategy_vs_mcftrr,
    _transition_subtitle,
    load_q_values,
    plot_q1_minus_mcftrr,
    plot_q1_q4_dynamics,
    plot_quartile_transitions,
    plot_registry_figure,
    transition_sankey_payloads,
)
from viz.series_registry import (
    q1_signals,
    topn_fan_concentration,
    weight_sweep,
)

# Custom-bundled plotly.min.js (scatter+bar+sankey only). Pinned by SHA so a
# silent swap to the 4.7 MB full bundle is caught in tests.
PLOTLY_BUNDLE_SHA256 = "95aecfee38073f2dc471f65a839e826e464322e15cd3f1046b9de8b6b3308775"
PLOTLY_BUNDLE_FILENAME = "plotly.min.js"

NAV_LINKS: list[tuple[str, str]] = [
    ("Home", "index.html"),
    ("Q1–Q4 dynamics", "q1_q4_dynamics.html"),
    ("Q1 vs MCFTRR alpha", "q1_minus_mcftrr.html"),
    ("Quartile composition", "q_history.html"),
    ("Quartile flows", "transitions.html"),
    ("Methodology", "methodology.html"),
    ("Experiments", "compare.html"),
    ("Mages index", "mages_index.html"),
]

# Rendered only when their inputs are present, so their nav entries have to drop
# out with them — a clone without the research CSVs must not get 404s in every header.
OPTIONAL_PAGES = frozenset({"compare.html", "mages_index.html"})


def _nav_links(rendered_optional: set[str]) -> list[tuple[str, str]]:
    return [
        (label, href)
        for label, href in NAV_LINKS
        if href not in OPTIONAL_PAGES or href in rendered_optional
    ]


def _env() -> Environment:
    return Environment(
        loader=PackageLoader("viz", "templates"),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


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


def _load_scores(path: Path | None) -> dict[str, dict[str, float]]:
    """Read scores.csv → {month: {ticker: score}} (full precision). Missing → empty."""
    if path is None or not path.exists():
        return {}
    out: dict[str, dict[str, float]] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            month, ticker, score = (row[f] for f in SCORES_FIELDS)
            out.setdefault(month, {})[ticker] = float(score)
    return out


def _order_by_score(members: list[str], month_scores: dict[str, float]) -> list[str]:
    """Rank by full-precision score DESC, ties → ticker ASC (matches
    `quartile_split`). Members without a score keep the tail in input order."""
    scored = sorted(
        (t for t in members if t in month_scores),
        key=lambda t: (-month_scores[t], t),
    )
    return scored + [t for t in members if t not in month_scores]


def _top15_assets(
    scores: dict[str, dict[str, float]],
    monthly_dir: Path | None,
    q_values: pd.DataFrame,
    label: str,
) -> tuple[pd.Series | None, str]:
    """Q1 top15 NAV (reindexed to q_values) + its alpha-chart embed.

    Computed inline from scores + the monthly panel, so the page never depends on
    the research-only concentration CSV. The NAV feeds the extra line on the home
    dynamics chart; the embed sits below the Q1 alpha chart. Absent scores
    (pre-task-025 output) or panel → (None, "") and both are skipped.
    """
    if not scores or monthly_dir is None:
        return None, ""
    nav = top_k_nav_from_scores(scores, monthly_dir, k=TOP_K_CONCENTRATION)
    if nav is None:
        return None, ""
    top15 = nav.reindex(q_values.index)
    frame = pd.DataFrame({label: top15, "MCFTRR": q_values["MCFTRR"]})
    fig = _plot_strategy_vs_mcftrr(
        frame, label, strat_name=label, title=f"{label} vs MCFTRR alpha", strat_color=Q1_TOP15_COLOR
    )
    return top15, _chart_embed(fig, div_id="chart-top15-alpha")


def _build_data_json(
    holdings: dict[str, dict[str, list[str]]],
    tickers: dict[str, Any],
    pending: dict[str, list[dict[str, Any]]],
    universe_meta: dict[str, dict[str, Any]],
    scores: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """Embed canonical names inline so q_history.html needs no extra fetch.

    INVARIANT (task 025): the Q1-Q4 array order is the authoritative rank by
    FULL-precision score (DESC, ties → ticker ASC) — the same key as
    `quartile_split`/`score_ranking`, so a top-K slice matches task 024. The
    score VALUE is not shipped: order alone carries the rank. The page restores
    this order for "sort by q-factor" and re-sorts by ticker for "sort by name";
    it must never reconstruct the rank any other way. Without scores (older
    output) rows keep the holdings' alphabetical order — backward compatible.
    """
    months = sorted(holdings)
    out_holdings: dict[str, dict[str, list[list[str]]]] = {}
    for m in months:
        month_scores = scores.get(m, {})
        per_q: dict[str, list[list[str]]] = {}
        for q in ("Q1", "Q2", "Q3", "Q4"):
            ordered = _order_by_score(holdings[m].get(q, []), month_scores)
            per_q[q] = [[t, _canonical(tickers, t)] for t in ordered]
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


def _heading_slug(text: str) -> str:
    """`## Ограничения` → `ограничения`. Cyrillic is kept: browsers percent-encode
    the fragment, and a transliteration table would be one more thing to maintain."""
    out = "".join(c.lower() if c.isalnum() else "-" for c in text.strip())
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")


def _render_methodology_md(md_path: Path) -> str:
    """Render, giving every heading an id so other pages can deep-link a section."""
    md = MarkdownIt("commonmark", {"html": False}).enable("table")
    tokens = md.parse(md_path.read_text(encoding="utf-8"))
    for i, token in enumerate(tokens):
        if token.type == "heading_open" and i + 1 < len(tokens):
            token.attrSet("id", _heading_slug(tokens[i + 1].content))
    rendered: str = md.renderer.render(tokens, md.options, {})
    return rendered


def _fan_embed(concentration_path: Path | None) -> str:
    """Embed for the optional concentration fan (task 024). Missing CSV → empty
    string, so the template skips that section."""
    if not (concentration_path and concentration_path.exists()):
        return ""
    fig = plot_registry_figure(
        topn_fan_concentration(path=concentration_path),
        title="Концентрация: top-K из top-100, K 5…30",
        gradient=True,
    )
    return _chart_embed(fig, div_id="chart-topn-concentration")


def _mages_page_context(
    holdings: dict[str, dict[str, list[str]]],
    tickers: dict[str, Any],
    *,
    mages_dir: Path | None,
    monthly_dir: Path | None,
    indices_dir: Path | None,
    mages_intro_md: Path | None,
    mages_methodology_md: Path | None,
) -> dict[str, Any] | None:
    """Context for mages_index.html (task 002), or None when its inputs (data +
    price panel + benchmark) are absent — a repo without data/mages just omits it."""
    if not (mages_dir and monthly_dir and indices_dir and any(mages_dir.glob("*.json"))):
        return None
    quarters = load_quarters(mages_dir)
    frame = build_mages_frame(quarters, monthly_dir=monthly_dir, indices_dir=indices_dir)
    if frame.empty:
        return None
    wframe = build_weighted_frame(
        holdings, quarters, monthly_dir=monthly_dir, indices_dir=indices_dir
    )
    wframe["Mages"] = frame["Mages"]  # overlay the pure mages curve on chart 2
    table = build_mages_table(holdings, quarters, lambda t: _canonical(tickers, t))
    intro = (
        _render_methodology_md(mages_intro_md) if mages_intro_md and mages_intro_md.exists() else ""
    )
    methodology = (
        _render_methodology_md(mages_methodology_md)
        if mages_methodology_md and mages_methodology_md.exists()
        else ""
    )
    # Escape < so a name containing "</script>" can't break out of the inline JSON.
    table_json = json.dumps(table, ensure_ascii=False, separators=(",", ":"))
    table_json = table_json.replace("<", "\\u003c")
    return {
        "title": "Mages index",
        "intro_html": intro,
        "chart_mages": _chart_embed(plot_mages_vs_mcftrr(frame), div_id="chart-mages"),
        "chart_weighted": _chart_embed(plot_weighted_q1(wframe), div_id="chart-weighted"),
        "table_json": table_json,
        "table_lam": f"{table['lam']:g}",
        "methodology_html": methodology,
    }


def _compare_page_context(
    simple_path: Path,
    curve_fit_path: Path,
    sweep_path: Path,
    fan_concentration_path: Path | None,
) -> dict[str, Any]:
    """Experiments page (task 20): headline signals + weight-sweep + the optional
    concentration fan (task 024)."""
    headline = q1_signals(simple_path=simple_path, curve_fit_path=curve_fit_path)
    sweep = weight_sweep(sweep_path=sweep_path)
    fig_headline = plot_registry_figure(headline, title="Strategy comparison")
    fig_sweep = plot_registry_figure(
        sweep,
        title="The momentum effect holds for any weighting",
        gradient=True,
        formula="score = (a·r(12-1) + (1−a)·r(6-1)) / σ(12),  a = 1.0 … 0.0",
    )
    return {
        "title": "Experiments",
        "chart_headline": _chart_embed(fig_headline, div_id="chart-compare-headline"),
        "chart_sweep": _chart_embed(fig_sweep, div_id="chart-compare-sweep"),
        "chart_topn_concentration": _fan_embed(fan_concentration_path),
    }


def _headline_numbers(q_values: pd.DataFrame) -> dict[str, str]:
    """Terminal multiple and CAGR for Q1 and the benchmark.

    Generated at build time rather than written into a doc: the values move with
    every monthly refresh, and a hand-typed one goes stale within days.
    """
    years = (q_values.index.max() - q_values.index.min()).n / 12
    out: dict[str, str] = {"years": f"{years:.1f}"}
    for col, key in (("Q1", "q1"), ("MCFTRR", "bench")):
        terminal = float(q_values[col].iloc[-1])
        out[f"{key}_x"] = f"{terminal:.2f}"
        out[f"{key}_cagr"] = f"{terminal ** (1 / years) - 1:.1%}" if years > 0 else "—"
    return out


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
    fan_concentration_path: Path | None = None,
    pending_path: Path | None = None,
    universe_meta_path: Path | None = None,
    scores_path: Path | None = None,
    mages_dir: Path | None = None,
    monthly_dir: Path | None = None,
    indices_dir: Path | None = None,
    mages_intro_md: Path | None = None,
    mages_methodology_md: Path | None = None,
) -> dict[str, Path]:
    """Render the full site to `out_dir`. Returns map of logical name → path.

    `compare_*_path` are signal-independent sources for the explorer page
    (task 20): when all three exist, compare.html is rendered. `fan_concentration_path`
    adds the optional concentration fan (task 024) to that page when present. The
    per-signal pages above stay tied to `signal`."""
    env = _env()
    q_values = load_q_values(q_values_path)
    holdings = _load_holdings(holdings_dir)
    tickers = load_tickers(tickers_path)
    scores = _load_scores(scores_path)
    top15_label = f"Q1 top{TOP_K_CONCENTRATION}"
    top15, embed_t15_alpha = _top15_assets(scores, monthly_dir, q_values, top15_label)

    dyn_extra = [(top15_label, top15, Q1_TOP15_COLOR)] if top15 is not None else None
    fig_dyn = plot_q1_q4_dynamics(q_values, extra_series=dyn_extra)
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
    headline = _headline_numbers(q_values)
    build_iso = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC")

    pages: dict[str, Path] = {}

    # Decided before the first render: every page carries the same header.
    mages_ctx = _mages_page_context(
        holdings,
        tickers,
        mages_dir=mages_dir,
        monthly_dir=monthly_dir,
        indices_dir=indices_dir,
        mages_intro_md=mages_intro_md,
        mages_methodology_md=mages_methodology_md,
    )
    compare_ready = bool(compare_simple_path and compare_curve_fit_path and compare_sweep_path)
    optional_rendered = {"mages_index.html"} if mages_ctx is not None else set()
    if compare_ready:
        optional_rendered.add("compare.html")
    nav_links = _nav_links(optional_rendered)

    def render(name: str, template: str, ctx: dict[str, Any]) -> None:
        full_ctx = {
            "nav_links": nav_links,
            "current_href": name,
            **ctx,
        }
        html = env.get_template(template).render(**full_ctx)
        path = out_dir / name
        write_text_atomic(path, html)
        pages[name] = path

    render(
        "index.html",
        "index.html",
        {
            "title": "Home",
            "chart_dyn": embed_dyn_idx,
            "top15_label": top15_label if top15 is not None else None,
            "top15_k": TOP_K_CONCENTRATION,
            "compare_available": compare_ready,
            "chart_alpha": embed_alpha_idx,
            "build_iso": build_iso,
            "headline": headline,
            "first_month": first_month,
            "last_month": last_month,
        },
    )
    render(
        "q1_q4_dynamics.html",
        "chart.html",
        {"title": "Q1–Q4 dynamics", "chart_html": embed_dyn_solo},
    )
    # Q1 top15 alpha (task 026) sits below the Q1 alpha chart on this page, not as
    # its own page — both share the "strategy vs MCFTRR alpha" framing.
    render(
        "q1_minus_mcftrr.html",
        "chart.html",
        {
            "title": "Q1 vs MCFTRR alpha",
            "chart_html": embed_alpha_solo,
            "chart_html_2": embed_t15_alpha,
        },
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

    if mages_ctx is not None:
        render("mages_index.html", "mages_index.html", mages_ctx)

    if compare_simple_path and compare_curve_fit_path and compare_sweep_path:
        render(
            "compare.html",
            "compare.html",
            _compare_page_context(
                compare_simple_path,
                compare_curve_fit_path,
                compare_sweep_path,
                fan_concentration_path,
            ),
        )

    data_json = _build_data_json(
        holdings,
        tickers,
        _load_pending(pending_path),
        _load_universe_meta(universe_meta_path),
        scores,
    )
    data_path = out_dir / "data.json"
    write_text_atomic(
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
    "OPTIONAL_PAGES",
    "PLOTLY_BUNDLE_FILENAME",
    "PLOTLY_BUNDLE_SHA256",
    "build_site",
    "default_bundle_path",
    "default_methodology_path",
]
