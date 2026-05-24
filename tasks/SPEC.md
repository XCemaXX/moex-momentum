# Specification: Momentum pipeline for Russian equities

> Historical requirements document. Some clauses predate later locked decisions
> (e.g. §2.4 describes the early universe rule; the shipped pipeline uses a
> top-100-liquid universe and a union of MOEX boards). See `docs/methodology.md`
> for the current, authoritative method.

## 1. Goal

An automated pipeline that collects Russian equity-market data, computes a
momentum strategy following the t.me/kpd_investments method, and renders charts
matching the reference images (`raw_sources/momentum_*.jpg`):
1. Q1–Q4 quartile dynamics versus MCFTRR.
2. Cumulative Q1−Q4 momentum premium.
3. Cumulative spread of Q1 over MCFTRR.

## 2. Functional requirements

### 2.1 Data collection

Sources are chosen during a research phase via web search; sites must be large
and reliable:

- **Quotes** — MOEX ISS API (daily).
- **MCFTRR index** — MOEX ISS API.
- **Dividends** — MOEX ISS as primary; gaps are filled by the Claude skill
  `/fill-dividends` via research on Smart-Lab / dohod.ru / e-disclosure.
- **Splits** — symmetrically: MOEX as primary, Claude skill `/fill-splits` for
  gaps. A detector in the code catches suspicious days.

### 2.2 Data storage

- Plain-text format, readable without special editors.
- JSONL **per ticker** (`data/prices/{TICKER}.jsonl`,
  `data/dividends/{TICKER}.jsonl`, …).
- `data/tickers.json` — ticker dictionary:
  `ticker → {canonical, aliases, type, board, history, delisted_after}`. One
  canonical name, several aliases (to match "МосБиржа" / "Московская биржа" /
  "MOEX"). The `history` field handles rebrandings (TCSG → T).
- The current `raw_sources/Российские_акции_*.csv` is NOT used in production;
  it stays in place only for regression validation.
- Build artifacts (HTML previews, caches) are gitignored. The JSONL files
  themselves are committed.

### 2.3 Momentum computation

Following the t.me/kpd_investments method:
- Curve-fit formula (default): `(0.9·r(12-1) + 0.1·r(6-1)) / σ(12)`.
- Simple formula: `r(12-1) / σ(12)`.
- Ability to switch formulas and to add new signals easily (designed for future
  features: the "mages index" as a strategy, overlays).
- Taxes and transaction costs: 13% dividend tax, 0.05% commission per side.
  The numbers live in a single `config.py`, the only source of truth; do not
  scatter them across the code.

### 2.4 Stock universe

Survivorship-free:
- The basket is recomputed for every month.
- Inclusion condition: a ticker has ≥13 consecutive month-end closes ending in
  the current month.
- No turnover/liquidity filter (if delisted, the data simply ends and the ticker
  drops out by itself).
- Equities only (`board=TQBR`); bonds and OFZ are excluded from momentum and
  reserved for a separate branch for the future "mages index" feature.

### 2.5 Splits

- No adjustment is baked into prices upstream — raw prices are stored and
  corrected on the fly.
- The detector flags days with |return| > 30% not explained by a dividend or a
  recorded split → fail-loud, never silently corrected.
- Filling via a Claude skill, symmetric with dividends.

### 2.6 Visualization and deployment

- HTML via Plotly with `include_plotlyjs='directory'` (one shared
  `plotly.min.js`, no CDN, everything works offline).
- No kaleido (it pulls in chromium).
- README — text links to the HTML pages only.
- Site on GitHub Pages: a landing page with three charts + historical
  navigation across Q1–Q4 (any past month) + methodology. Deployed via GitHub
  Actions.
- On the site, ticker display format: `YDEX (Яндекс)` (ticker + canonical name
  from the dictionary).

### 2.7 Reproducibility

- Idempotent CLI steps: `momentum ingest prices`, `… dividends`,
  `… indices`, `momentum compute backtest`, `momentum site build`. Re-running
  produces no duplicates and no mutations.
- `bash scripts/setup.sh` brings the project up immediately after `git clone`
  (Linux/WSL).

## 3. Non-functional requirements

### 3.1 Stack

- **Python 3.12**.
- **uv** for the venv and lockfile (`uv lock` is committed; CI uses
  `uv sync --frozen`).
- HTTP client: **httpx** (not requests).
- Data: **pandas**.
- Visualization: **plotly** + **jinja2** for templates.
- CLI: **typer**.
- Tests: **pytest**.
- Linters: **ruff**, **mypy** (strict for `src/momentum/**`).
- Config: `pyproject.toml` (no separate setup.py / requirements.txt).

### 3.2 Architecture

- Inside the project, Python only; bash is used only for one-shot
  initialization.
- No Makefile.
- `src/momentum/` structure: ingest / corporate / compute / viz — each block is
  isolated and tested separately.
- All pure functions: clean input → output, no global mutations.
- Atomic JSONL writes: `.tmp` + `os.replace` (no half-written files after a
  network blip).

### 3.3 Data quality

- Logging of every ingest operation (ticker, rows_added, source, duration_ms).
- Split sanity-detector — auto-WARN after ingest, hard-fail in `--strict` mode
  (for CI).
- Regression anchors: VSMO 2022-03 simple signal = 4.6458% (from info.txt,
  externally verified) ± 0.05%; LKOH/SBER r(12-1) on 2023-12 — snapshot anchors
  (self-computed, frozen in `tests/test_momentum_examples.py`).
- Cross-check against the legacy CSV from `raw_sources/` — 25 points, tolerance
  ±0.5%.

## 4. Future features (separate tasks)

See `tasks/todo/`:
- `001_quartile_transitions.md` — a visual representation of tickers flowing
  between Q1↔Q4 month to month, plus "sticky" tickers with an
  exponentially-decaying weight.
- `002_mages_index.md` — ingest the mages index from images (Claude skill
  `/parse_mages_index`), display it, overlay it on Q1, comparison features.
- `003_chart_modes.md` — two chart modes: cumulative index (as now) +
  month-by-month bar comparison of Q1 vs MCFTRR.

The core pipeline architecture must allow for these features:
- A `Signal` protocol — to add new strategies without changing backtest code.
- Holdings per month are stored (needed for transitions).
- A tickers dict with alias resolution — for matching the mages index.
- Charts select their visualization mode (cumulative / per-month) —
  parameterized in `viz`.

## 5. What already exists

- `raw_sources/info.txt` — the method and two regression anchors:
  - VSMO 2022-03 simple signal = 4.6458% (a numeric example with 12 prices in
    the file body).
  - The author's Q1–Q4 breakdown as of 31.03.2026 (in the file header) — after
    running the backtest for that as-of date our lists should roughly match
    (discrepancies are expected due to the survivorship-free universe).
- `raw_sources/momentum_*.jpg` — reference images (the exact numbers are not
  reproducible due to the survivorship-free universe — by design).
- `raw_sources/индекс_магов_*.txt` — the format for the future feature.
- `raw_sources/Российские_акции_*.csv` — legacy data for regression validation
  (UTF-8, recovered).
