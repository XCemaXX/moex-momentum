"""Phase 11 — static-site builder."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from storage.records import write_records_atomic
from storage.schemas import Q_VALUES_FIELDS
from viz.site_builder import (
    NAV_LINKS,
    PLOTLY_BUNDLE_FILENAME,
    build_site,
)

# Page filenames the builder must emit.
_PAGES = {
    "index.html",
    "q1_q4_dynamics.html",
    "q1_minus_mcftrr.html",
    "transitions.html",
    "q_history.html",
    "methodology.html",
}


@pytest.fixture
def fixture_dir(tmp_path: Path) -> Path:
    """Self-contained fixture: q_values, holdings, tickers, methodology, bundle."""
    months = pd.period_range("2022-01", "2023-12", freq="M")
    q_path = tmp_path / "q_values.csv"
    q_rows = [
        {
            "month": str(p),
            "Q1": 1.0 * 1.012**i,
            "Q2": 1.0 * 1.006**i,
            "Q3": 1.0 * 1.000**i,
            "Q4": 1.0 * 0.994**i,
            "MCFTRR": 1.0 * 1.008**i,
        }
        for i, p in enumerate(months)
    ]
    write_records_atomic(q_path, q_rows, fieldnames=Q_VALUES_FIELDS)

    holdings_dir = tmp_path / "holdings"
    holdings_dir.mkdir()
    for p in months:
        (holdings_dir / f"{p}.json").write_text(
            json.dumps(
                {
                    "Q1": ["AKRN", "SBER"],
                    "Q2": ["GAZP"],
                    "Q3": ["LKOH"],
                    "Q4": ["VTBR", "RTKM"],
                }
            ),
            encoding="utf-8",
        )

    tickers = {
        "AKRN": {"canonical": "Акрон", "aliases": [], "boards": [], "type": "share"},
        "SBER": {"canonical": "Сбербанк", "aliases": [], "boards": [], "type": "share"},
        "GAZP": {"canonical": "Газпром", "aliases": [], "boards": [], "type": "share"},
        "LKOH": {"canonical": "Лукойл", "aliases": [], "boards": [], "type": "share"},
        "VTBR": {"canonical": "ВТБ", "aliases": [], "boards": [], "type": "share"},
        "RTKM": {"canonical": "Ростелеком", "aliases": [], "boards": [], "type": "share"},
    }
    tickers_path = tmp_path / "tickers.json"
    tickers_path.write_text(json.dumps(tickers, ensure_ascii=False), encoding="utf-8")

    md_path = tmp_path / "methodology.md"
    md_path.write_text(
        "# Title\n\nBody paragraph.\n\n## Section\n\n| A | B |\n|---|---|\n| 1 | 2 |\n",
        encoding="utf-8",
    )

    bundle_src = tmp_path / "plotly.min.js"
    bundle_src.write_bytes(b"/* fake bundle */\n")

    fixture_dir.q_path = q_path  # type: ignore[attr-defined]
    fixture_dir.holdings_dir = holdings_dir  # type: ignore[attr-defined]
    fixture_dir.tickers_path = tickers_path  # type: ignore[attr-defined]
    fixture_dir.md_path = md_path  # type: ignore[attr-defined]
    fixture_dir.bundle_src = bundle_src  # type: ignore[attr-defined]
    return tmp_path


def _build(tmp_path: Path, out_dir: Path) -> dict[str, Path]:
    return build_site(
        q_values_path=tmp_path / "q_values.csv",
        holdings_dir=tmp_path / "holdings",
        tickers_path=tmp_path / "tickers.json",
        methodology_md=tmp_path / "methodology.md",
        bundle_src=tmp_path / "plotly.min.js",
        out_dir=out_dir,
        signal="curve_fit",
    )


def test_all_pages_written(fixture_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    pages = _build(fixture_dir, out)
    for name in _PAGES:
        assert (out / name).exists(), f"{name} missing"
        assert name in pages
    assert (out / "data.json").exists()
    assert (out / PLOTLY_BUNDLE_FILENAME).exists()


def test_no_cdn_anywhere(fixture_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    _build(fixture_dir, out)
    for f in out.glob("*.html"):
        text = f.read_text(encoding="utf-8")
        assert "cdn.plot" not in text, f"{f.name} references CDN"
        assert "https://cdn" not in text, f"{f.name} references CDN"


def test_each_page_loads_bundle_once(fixture_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    _build(fixture_dir, out)
    for f in out.glob("*.html"):
        text = f.read_text(encoding="utf-8")
        # Exactly one <script src="plotly.min.js"> in <head>.
        assert text.count('src="plotly.min.js"') == 1, f"{f.name}: bundle load count wrong"


def test_nav_consistent_with_constant(fixture_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    _build(fixture_dir, out)
    expected_hrefs = {href for _label, href in NAV_LINKS}
    for f in out.glob("*.html"):
        text = f.read_text(encoding="utf-8")
        for href in expected_hrefs:
            assert f'href="{href}"' in text, f"{f.name} missing nav link {href}"


def test_current_page_highlighted(fixture_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    _build(fixture_dir, out)
    for name in _PAGES:
        text = (out / name).read_text(encoding="utf-8")
        assert f'href="{name}" class="current"' in text, (
            f"{name} should mark itself as current in nav"
        )


def test_index_embeds_two_charts(fixture_dir: Path, tmp_path: Path) -> None:
    """Dynamics + alpha are the two charts embedded on the landing page."""
    out = tmp_path / "out"
    _build(fixture_dir, out)
    text = (out / "index.html").read_text(encoding="utf-8")
    assert text.count("Plotly.newPlot") == 2


def test_data_json_shape(fixture_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    _build(fixture_dir, out)
    data = json.loads((out / "data.json").read_text(encoding="utf-8"))
    assert "months" in data and "holdings" in data
    assert data["months"] == sorted(data["months"])
    assert data["months"][0] == "2022-01"
    assert data["months"][-1] == "2023-12"
    # Per-month structure: {Q1: [[ticker, canonical], ...], Q2: ..., Q3: ..., Q4: ...}
    sample = data["holdings"]["2022-06"]
    for q in ("Q1", "Q2", "Q3", "Q4"):
        assert q in sample
        for row in sample[q]:
            assert isinstance(row, list) and len(row) == 2
            ticker, canonical = row
            assert isinstance(ticker, str)
            assert isinstance(canonical, str)
    # Canonical comes from tickers.json — check one entry.
    q1 = sample["Q1"]
    assert ["AKRN", "Акрон"] in q1
    assert ["SBER", "Сбербанк"] in q1


def test_data_json_unknown_ticker_canonical_empty(tmp_path: Path) -> None:
    """A ticker present in holdings but absent from tickers.json gets empty canonical."""
    months = pd.period_range("2022-01", "2022-06", freq="M")
    q_path = tmp_path / "q_values.csv"
    write_records_atomic(
        q_path,
        [
            {"month": str(p), "Q1": 1.0, "Q2": 1.0, "Q3": 1.0, "Q4": 1.0, "MCFTRR": 1.0}
            for p in months
        ],
        fieldnames=Q_VALUES_FIELDS,
    )
    holdings_dir = tmp_path / "holdings"
    holdings_dir.mkdir()
    (holdings_dir / "2022-06.json").write_text(
        json.dumps({"Q1": ["GHOST"], "Q2": [], "Q3": [], "Q4": []}), encoding="utf-8"
    )
    for p in months[:-1]:
        (holdings_dir / f"{p}.json").write_text(
            json.dumps({"Q1": [], "Q2": [], "Q3": [], "Q4": []}), encoding="utf-8"
        )
    (tmp_path / "tickers.json").write_text("{}", encoding="utf-8")
    (tmp_path / "methodology.md").write_text("# x\n", encoding="utf-8")
    (tmp_path / "plotly.min.js").write_bytes(b"")

    out = tmp_path / "out"
    _build(tmp_path, out)
    data = json.loads((out / "data.json").read_text(encoding="utf-8"))
    assert data["holdings"]["2022-06"]["Q1"] == [["GHOST", ""]]


def test_methodology_renders_markdown(fixture_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    _build(fixture_dir, out)
    text = (out / "methodology.html").read_text(encoding="utf-8")
    # Headings + paragraph + table from the fixture markdown.
    assert "<h1>Title</h1>" in text
    assert "<p>Body paragraph.</p>" in text
    assert "<table>" in text and "<th>A</th>" in text
    # No raw markdown leaked through.
    assert "# Title" not in text
    assert "|---|" not in text


def test_bundle_copied_when_dest_differs(fixture_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    _build(fixture_dir, out)
    copied = (out / PLOTLY_BUNDLE_FILENAME).read_bytes()
    assert copied == (fixture_dir / PLOTLY_BUNDLE_FILENAME).read_bytes()


def test_bundle_inplace_is_noop(fixture_dir: Path, tmp_path: Path) -> None:
    """If bundle_src is already inside out_dir, don't copy onto itself."""
    out = tmp_path / "out"
    out.mkdir()
    bundle_inside = out / PLOTLY_BUNDLE_FILENAME
    bundle_inside.write_bytes(b"existing bundle content")
    build_site(
        q_values_path=fixture_dir / "q_values.csv",
        holdings_dir=fixture_dir / "holdings",
        tickers_path=fixture_dir / "tickers.json",
        methodology_md=fixture_dir / "methodology.md",
        bundle_src=bundle_inside,
        out_dir=out,
        signal="curve_fit",
    )
    assert bundle_inside.read_bytes() == b"existing bundle content"


def test_chart_pages_full_size_each(fixture_dir: Path, tmp_path: Path) -> None:
    """Each standalone chart page has its own embedded Plotly figure."""
    out = tmp_path / "out"
    _build(fixture_dir, out)
    for name in ("q1_q4_dynamics.html", "q1_minus_mcftrr.html", "transitions.html"):
        text = (out / name).read_text(encoding="utf-8")
        assert text.count("Plotly.newPlot") == 1, f"{name}: expected 1 chart"


def test_transitions_page_has_sankey_and_sticky(fixture_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    _build(fixture_dir, out)
    text = (out / "transitions.html").read_text(encoding="utf-8")
    assert '"type":"sankey"' in text
    # One sticky-card grid (4 quartiles) per period window; "all" always present.
    cards = text.count('class="sticky-card"')
    assert cards >= 4 and cards % 4 == 0
    assert 'data-window="all"' in text
    assert "AKRN" in text and "Акрон" in text


def test_transitions_period_buttons_drive_both(fixture_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    _build(fixture_dir, out)
    text = (out / "transitions.html").read_text(encoding="utf-8")
    # Period buttons exist and the embedded payload lets JS restyle the Sankey.
    assert 'class="period-bar"' in text
    assert "Plotly.restyle" in text
    # 24-month fixture → only the 1y window fits besides "all".
    assert text.count('class="sticky-set"') == 2
    # Selected period is shown by the sticky list, and the chart can collapse.
    assert 'id="sticky-period"' in text and "data-period=" in text
    assert 'id="toggle-chart"' in text


def test_q_history_references_data_json(fixture_dir: Path, tmp_path: Path) -> None:
    """q_history.html fetches data.json client-side."""
    out = tmp_path / "out"
    _build(fixture_dir, out)
    text = (out / "q_history.html").read_text(encoding="utf-8")
    assert 'fetch("data.json")' in text
    assert 'id="month-select"' in text
    assert 'id="q-grid"' in text


def test_q_history_has_q1_diff_section(fixture_dir: Path, tmp_path: Path) -> None:
    """Task 004 — Q1 buy/sell diff vs previous month."""
    out = tmp_path / "out"
    _build(fixture_dir, out)
    text = (out / "q_history.html").read_text(encoding="utf-8")
    assert 'id="q1-diff"' in text
    # Diff JS computes both directions.
    assert "currQ1Set" in text and "prevQ1Set" in text
    # Reason strings live in JS for both transitions and edge cases.
    assert "был в " in text
    assert "ушёл в " in text
    assert "делистнут" in text
    assert "новичок" in text


def _write_compare_sources(tmp_path: Path) -> tuple[Path, Path, Path]:
    """simple + curve_fit q_values.csv and a sweep q1_nav.csv for compare.html."""
    months = pd.period_range("2022-01", "2023-12", freq="M")
    simple = tmp_path / "simple_q.csv"
    cf = tmp_path / "cf_q.csv"
    for path, q1_rate in ((simple, 1.013), (cf, 1.011)):
        write_records_atomic(
            path,
            [
                {
                    "month": str(p),
                    "Q1": q1_rate**i,
                    "Q2": 1.006**i,
                    "Q3": 1.0,
                    "Q4": 0.994**i,
                    "MCFTRR": 1.008**i,
                }
                for i, p in enumerate(months)
            ],
            fieldnames=Q_VALUES_FIELDS,
        )
    a_weights = [round(1.0 - 0.1 * k, 1) for k in range(11)]
    sweep = tmp_path / "sweep.csv"
    cols = [f"a{a:.2f}" for a in a_weights]
    write_records_atomic(
        sweep,
        [
            {
                "month": str(p),
                **{f"a{a:.2f}": (1.0 + 0.013 * a) ** i for a in a_weights},
                "MCFTRR": 1.008**i,
            }
            for i, p in enumerate(months)
        ],
        fieldnames=["month", *cols, "MCFTRR"],
    )
    return simple, cf, sweep


def test_compare_page_two_charts_and_series(fixture_dir: Path, tmp_path: Path) -> None:
    """compare.html renders both figures; sweep has 11 a/b traces + benchmark."""
    out = tmp_path / "out"
    simple, cf, sweep = _write_compare_sources(tmp_path)
    build_site(
        q_values_path=fixture_dir / "q_values.csv",
        holdings_dir=fixture_dir / "holdings",
        tickers_path=fixture_dir / "tickers.json",
        methodology_md=fixture_dir / "methodology.md",
        bundle_src=fixture_dir / "plotly.min.js",
        out_dir=out,
        signal="curve_fit",
        compare_simple_path=simple,
        compare_curve_fit_path=cf,
        compare_sweep_path=sweep,
    )
    text = (out / "compare.html").read_text(encoding="utf-8")
    assert text.count("Plotly.newPlot") == 2
    # Endpoint annotations prove the sweep ran with the production-signal labels.
    assert "(= simple)" in text
    assert "(= curve_fit)" in text
    # Both signal Q1 lines present in the headline figure.
    assert "Q1 simple" in text


def test_compare_skipped_without_sources(fixture_dir: Path, tmp_path: Path) -> None:
    """No compare sources → no compare.html (per-signal pages unaffected)."""
    out = tmp_path / "out"
    pages = _build(fixture_dir, out)
    assert "compare.html" not in pages
    assert not (out / "compare.html").exists()


def test_idempotent_build(fixture_dir: Path, tmp_path: Path) -> None:
    """Two builds in a row produce identical bytes (modulo build_iso in index)."""
    out = tmp_path / "out"
    _build(fixture_dir, out)
    first = {
        f.name: f.read_bytes()
        for f in out.glob("*")
        if f.suffix in {".html", ".json"} and f.name != "index.html"
    }
    _build(fixture_dir, out)
    second = {
        f.name: f.read_bytes()
        for f in out.glob("*")
        if f.suffix in {".html", ".json"} and f.name != "index.html"
    }
    assert first.keys() == second.keys()
    for name, value in first.items():
        assert value == second[name], f"{name} differs between builds"
