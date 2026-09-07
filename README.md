# moex-momentum

A reproducible pipeline for a **quartile momentum strategy on Russian equities (MOEX)**.
It ingests daily prices, dividends and splits from the MOEX ISS API, applies
corporate-action adjustments, computes a monthly momentum signal, sorts the
liquid universe into quartiles Q1–Q4, backtests them against the MCFTRR total-return
benchmark, and publishes interactive charts to GitHub Pages.

**Live charts:** https://xcemaxx.github.io/moex-momentum/
**Methodology (full, in Russian):** [`docs/methodology.md`](docs/methodology.md)

> The momentum method follows the public approach of the
> [kpd_investments](https://t.me/kpd_investments) blog, reproduced here on an
> independent MOEX dataset. The data, code and universe rule (top-100 by
> liquidity) are this project's own.

The site also carries a side project — «Индекс магов», the equity sleeve of a
publicly-published portfolio tracked quarter by quarter against the same benchmark.
It is independent of the momentum backtest; its own write-ups are
[`docs/mages_intro.md`](docs/mages_intro.md) and
[`docs/mages_methodology.md`](docs/mages_methodology.md).

## The signal

```
score = (0.9 · r(12-1) + 0.1 · r(6-1)) / σ(12)
```

- `r(12-1)`, `r(6-1)` — geometric-mean monthly return over `[t-11 … t-1]` and
  `[t-5 … t-1]`, **excluding the last month** (skip-month, to drop the short-term
  reversal).
- `σ(12)` — sample standard deviation of monthly returns (simple, not log) over
  `[t-11 … t]`.

Stocks are ranked by `score`, split into four equal quartiles, rebalanced monthly.
Q1 is the high-momentum top, Q4 the bottom. The *why* (literature, skip-month,
σ-normalization, the empirical 0.9/0.1 weights) is in
[`docs/methodology.md`](docs/methodology.md) (in Russian).

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
momentum compute monthly                  # raw prices/divs/splits → monthly total returns
momentum compute backtest --signal curve_fit   # quartile sort + NAV
momentum compute backtest --signal simple      # the second signal, for compare.html
momentum compute sweep                    # Q1 across the a/b weight grid
momentum compute fan                      # top-K concentration fan
momentum site build                       # render docs/pages/*.html
```

Run the same checks CI does:

```bash
uv run ruff format --check
uv run ruff check
uv run mypy src
uv run pytest
```

### Monthly update

Run this once a month, in order. It is idempotent — reruns add only deltas.

```bash
# 1. Ticker dictionary — --force-refresh bypasses the cache (no TTL); without it
#    a month-old snapshot gives stale board windows → false delisted_after →
#    price ingest silently stalls.
momentum tickers refresh --force-refresh

# 2. Prices / splits / indices — delta pulls from the last stored date.
momentum ingest prices
momentum ingest splits --force-refresh
momentum ingest indices

# 3. Dividends. MOEX withdrew the ISS handle in 2025-10, so this step now
#    exits non-zero and only the external fill brings anything new.
momentum ingest dividends --force-refresh --months 3   # expected to fail; see task 054
momentum corporate check-registers --since <last month>  # which payouts are missing
momentum ingest fill-dividends --force-refresh -t <each ticker it named>

# 4. Apply curated fixes (_conflicts_resolved.json): drops known ISS dups,
#    applies disclosure corrections. Required after step 3.
momentum corporate apply-conflicts

# 5. Detector (WARN-only) + recompute + site.
momentum corporate detect      # flags |daily return| > 30% with no split/dividend
momentum compute monthly --from-scratch   # rebless baselines after ingest
momentum compute backtest --signal curve_fit
momentum compute backtest --signal simple
momentum compute sweep
momentum compute fan
momentum site build

# 6. Re-bless the regression reference: the new month makes `pytest` red on
#    purpose, and the one-row diff is the record of what it contributed.
cp data/momentum/curve_fit/q_values.csv tests/reference/q_values_curve_fit.csv
cp data/momentum/simple/q_values.csv    tests/reference/q_values_simple.csv
```

Notes:

- **The reference diff should be exactly one new row per signal.** More than that
  means the recompute moved history — a dividend backfill or a split fix — and the
  commit should say why.

- **ISS no longer serves dividends at all.** Every payout now arrives through
  `momentum ingest fill-dividends` (dohod, smart-lab) or a manual `augment` in
  `_conflicts_resolved.json`. `check-registers` is the only thing that tells a
  missing payout apart from a share that stopped paying — run it every month.
- `--since` on prices/indices is a **forward floor only**: it can skip ahead but
  never backfills a range already stored. To re-pull a suspect older range, delete
  those rows from the CSV first, then ingest.
- Editing `src/config.py` or `src/tickers.py` takes effect immediately (editable
  install); no reinstall needed.

### Dividend reconciliation (recurring)

ISS lags real payouts by months, so every cycle a few recent dividends are missing.
Resolving them has sharp edges — which source may be trusted for which share class,
when `augment` is safe, why a bulk fill drags in a name's entire history, and which
caches must never be deleted. That procedure lives in
`.claude/skills/update_monthly_data/references/reconcile_dividends.md`, together with
the price-ingest and recompute references next to it. Those files are the canonical
runbook; this README carries the command sequence only.

## CLI reference

The entry point is `momentum` (`cli:app`). Every command is idempotent.

| Command | Purpose |
|---|---|
| `momentum tickers refresh` | Bootstrap the ticker dictionary from ISS (`--force-refresh` to bypass the no-TTL cache) |
| `momentum tickers mark-unavailable` | Move empty-history tickers to the unavailable log |
| `momentum ingest prices` | Async fetch daily OHLCV from ISS (union of boards) |
| `momentum ingest splits` | Splits + bonus issues (ISS + manual override). `--force-refresh` is required monthly — the ISS cache key carries no date |
| `momentum ingest dividends` | Dividend payouts from ISS (`--months N` scopes the merge window); regenerate gap report |
| `momentum ingest fill-dividends` | Fill gaps from external sources (dohod.ru, …) |
| `momentum ingest indices` | Benchmark index series (default MCFTRR) |
| `momentum corporate detect` | Split/dividend anomaly detector (WARN-only; `--strict` to exit non-zero) |
| `momentum corporate apply-conflicts` | Apply `_conflicts_resolved.json` (drop/replace/augment) to dividend files |
| `momentum corporate check-registers` | MOEX register closings with no stored payout (`--strict` exits non-zero) |
| `momentum compute monthly` | Prices + adjustments → monthly total-return series |
| `momentum compute backtest` | Q1–Q4 quartile backtest (`--signal curve_fit\|simple`) |
| `momentum compute sweep` | Q1 NAV across the a/b weight grid (input for compare.html) |
| `momentum compute fan` | Top-K concentration fan (input for compare.html) |
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

(Fetcher pacing, detector thresholds and the ISS HTTP client have their own constants — see `src/config.py`.)

## Repository layout

```
src/
├── config.py          # single source of truth for constants
├── tickers.py         # ticker dictionary (canonical names + aliases)
├── ingest/            # data acquisition from MOEX ISS + external sources
├── adjustments/       # corporate-action processing (splits, dividends, detector)
├── momentum/          # signal computation + quartile backtest
├── storage/           # atomic CSV / JSON read/write
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
  The detector WARNs on unexplained jumps rather than silently adjusting; pass
  `--strict` to make it exit non-zero.
- **Committed dataset.** `data/` holds the raw source-of-truth; computed outputs
  (`data/momentum/`) and HTTP caches are gitignored and regenerable.
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

## Disclaimer

Research material, not investment advice. The quartile membership published by this
project is the output of the documented methodology applied to historical data; past
returns do not predict future ones, and the cost model is deliberately incomplete (see
the limitations section of the methodology). MIT covers the code, not the content.

## License

[MIT](LICENSE).
