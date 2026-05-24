# moex-momentum

A reproducible pipeline for a **quartile momentum strategy on Russian equities (MOEX)**.
It ingests daily prices, dividends and splits from the MOEX ISS API, applies
corporate-action adjustments, computes a monthly momentum signal, sorts the
liquid universe into quartiles Q1–Q4, backtests them against the MCFTRR total-return
benchmark, and publishes interactive charts to GitHub Pages.

**Live charts:** https://xcemaxx.github.io/moex-momentum/
**Methodology (full):** [`docs/methodology.md`](docs/methodology.md)

> The momentum method follows the public approach of the
> [kpd_investments](https://t.me/kpd_investments) blog, reproduced here on an
> independent MOEX dataset. The data, code and universe rule (top-100 by
> liquidity) are this project's own.

## The signal

```
score = (0.9 · r(12-1) + 0.1 · r(6-1)) / σ(12)
```

- `r(12-1)`, `r(6-1)` — total return over the 12- and 6-month windows, **excluding
  the last month** (skip-month, to drop the short-term reversal).
- `σ(12)` — sample standard deviation of monthly log-returns over the window.

Stocks are ranked by `score`, split into four equal quartiles, rebalanced monthly.
Q1 is the high-momentum top, Q4 the bottom. The *why* (literature, skip-month,
σ-normalization, the empirical 0.9/0.1 weights) is in
[`docs/methodology.md`](docs/methodology.md).

## Quickstart

Python 3.12 and Linux/WSL are required.

```bash
git clone https://github.com/xcemaxx/moex-momentum.git
cd moex-momentum
bash scripts/setup.sh          # creates .venv, installs uv inside it, uv sync --frozen
source .venv/bin/activate
```

The repository ships with the committed raw dataset, so the full strategy can be
**recomputed offline** without re-ingesting from the network:

```bash
momentum compute monthly       # raw prices/divs/splits → monthly total returns
momentum compute backtest      # quartile sort + NAV (default signal: curve_fit)
momentum site build            # render docs/pages/*.html
```

To refresh data from MOEX ISS (idempotent — re-running adds only deltas):

```bash
momentum tickers refresh
momentum ingest prices
momentum ingest splits
momentum ingest dividends
momentum ingest indices
momentum corporate detect      # flags |daily return| > 30% with no split/dividend
```

## CLI reference

The entry point is `momentum` (`cli:app`). Every command is idempotent.

| Command | Purpose |
|---|---|
| `momentum tickers refresh` | Bootstrap the ticker dictionary from ISS |
| `momentum tickers mark-unavailable` | Move empty-history tickers to the unavailable log |
| `momentum ingest prices` | Async fetch daily OHLCV from ISS (union of boards) |
| `momentum ingest splits` | Splits + bonus issues (ISS + manual override) |
| `momentum ingest dividends` | Dividend payouts from ISS; regenerate gap report |
| `momentum ingest fill-dividends` | Fill gaps from external sources (dohod.ru, …) |
| `momentum ingest indices` | Benchmark index series (default MCFTRR) |
| `momentum corporate detect` | Split/dividend anomaly detector (fail-loud) |
| `momentum compute monthly` | Prices + adjustments → monthly total-return series |
| `momentum compute backtest` | Q1–Q4 quartile backtest (`--signal curve_fit\|simple`) |
| `momentum site build` | Render the GitHub Pages site to `docs/pages/` |

## Configuration

`src/config.py` is the **single source of truth** for every tunable number — taxes,
fees, formula weights, universe and detector thresholds. Nothing is duplicated
elsewhere.

| Constant | Value | Meaning |
|---|---|---|
| `DIVIDEND_TAX` | `0.13` | Dividend withholding tax (RF resident) |
| `COMMISSION_PER_SIDE` | `0.0005` | Broker commission per trade side (0.05%) |
| `CURVE_FIT_A` / `CURVE_FIT_B` | `0.9` / `0.1` | Weights on r(12-1) and r(6-1) |
| `STDEV_DDOF` | `1` | Sample stdev (n−1) for σ(12) |
| `UNIVERSE_MIN_MONTHLY_CLOSES` | `13` | Min consecutive month-end closes to enter the universe |
| `UNIVERSE_TOP_N_LIQUID` | `100` | Universe size: N most liquid by median monthly turnover |
| `SUSPICIOUS_RETURN_THRESHOLD` | `0.30` | Daily-return threshold for the split/dividend detector |
| `ANALYSIS_START_DATE` | `2013-01-01` | Start of the backtest/visualization window |
| `INCREMENTAL_RECOMPUTE_MONTHS` | `12` | Trailing months recomputed by default |

(There are additional constants for an experimental persistence strategy and for the
ISS HTTP client — see `src/config.py`.)

## Repository layout

```
src/
├── config.py          # single source of truth for constants
├── tickers.py         # ticker dictionary (canonical names + aliases)
├── ingest/            # data acquisition from MOEX ISS + external sources
├── adjustments/       # corporate-action processing (splits, dividends, detector)
├── momentum/          # signal computation + quartile backtest
├── storage/           # atomic plain-text (JSONL/CSV) read/write
├── viz/               # Plotly charts + Jinja2 site builder
└── cli/               # Typer CLI subcommands
data/                  # committed raw dataset (prices, dividends, splits, indices)
docs/                  # GitHub Pages artifacts + methodology.md
tests/                 # pytest suite (regression anchors against known values)
```

The stack is fixed: Python 3.12, uv, httpx, pandas, plotly, jinja2, typer; pytest,
ruff, mypy for dev. No Makefile, no CDN — charts ship with a vendored `plotly.min.js`
and work offline. CI lints + tests on PRs and deploys Pages on push to `main`
(`.github/workflows/`).

## Data and reproducibility

- **Survivorship-free.** The universe is recomputed each month; delisted tickers
  fall out naturally when their prices end. No retrospective "winners" list.
- **Raw-first.** Prices are stored raw; splits/dividends are applied on the fly.
  The detector fails loud on unexplained jumps rather than silently adjusting.
- **Committed dataset.** `data/` holds the raw source-of-truth; computed outputs
  (`data/computed/`) and HTTP caches are gitignored and regenerable.
- **Regression anchors.** Tests freeze externally-verified values (e.g. VSMO
  2022-03 simple-signal = 4.6458%) to catch code drift.

## On the development process

This project was built largely with an **AI-assisted (agentic) workflow**, and that
history is kept in the repository on purpose, as a worked example:

- `tasks/` — the task journal (`SPEC.md`, `todo/`, `completed/`). Requirements,
  phase history and locked design decisions live here.
- `agent_context/` — internal research notes and generated reports produced while
  building the pipeline (data-source research, audits, legacy diffs).

These are working artifacts, not polished documentation — included for transparency
into how the pipeline was designed and verified.

## License

[MIT](LICENSE).
