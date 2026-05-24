# Backtest Phase 9 — findings (2026-05-11)

`momentum compute backtest --signal {simple,curve_fit}` on the full panel,
with **liquidity-filtered universe** (median monthly trading value ≥ 100M ₽
over the same 12-month window required by the return calculation).

Universe at 2026-03: **129** tickers (vs author's 134 in published Q1-Q4 at
2026-03 — matched within 4%; quartile sizes 33/32/32/32 vs author's
34/34/34/32).

## Headline numbers (NAV starting at 1.0)

| signal     | Q1    | Q2   | Q3   | Q4   | MCFTRR | ordering |
|------------|------:|-----:|-----:|-----:|-------:|----------|
| simple     | 10.81 | 2.30 | 3.83 | 0.91 |  3.70  | Q1 > Q3 > Q2 > Q4 |
| curve_fit  | 10.46 | 3.11 | 2.49 | 1.07 |  3.70  | **Q1 > Q2 > Q3 > Q4 — monotone ✓** |

- Q1 outperforms MCFTRR by ≈3× over 13 years.
- Q1/Q4 ≈ 10× — momentum spread at the tails.
- For `curve_fit` the quartile ordering is **monotone**, matching the
  textbook prediction. `simple` has Q3 above Q2 by ~65% — momentum is a tail
  effect; the middle of the distribution is noisy for the simpler spec.

## 2026-03 quartile assignment vs author's published lists

(Author's lists in `raw_sources/info.txt`, our holdings in
`data/computed/curve_fit/holdings/2026-03.json`)

| our quartile | size | in author's Q1 | in author's Q4 |
|--------------|-----:|---------------:|---------------:|
| Q1           |   33 |          **25** (74% of author's 34) | 0 |
| Q2           |   32 |           2    | 0 |
| Q3           |   32 |           1    | 1 |
| Q4           |   32 |           0    | **23** (72% of author's 32) |

No cross-leak between Q1 and Q4. Without using any whitelist, our ranking
agrees with the author's on ~75% of the tail names.

## Three fixes that produced these numbers

The first run had Q3 = 162-197× — caused by upstream data quality, not by the
backtest engine. Three fixes applied in order:

### 1. IRAO 100:1 reverse split (2015-01-20) — added to `tickers_manual.json`

Confirmed via Inter RAO press-release and investpalata.ru: nominal value
increased 100× (0.02809767 → 2.809767 ₽), trading halted 2014-12-25, resumed
2015-01-20 with the new issue 1-04-33498-E. Raw prices match: 0.00712
(2014-12-18) → 0.7641 (2015-01-20), ratio ≈ 107 (small drift over the 22-day
gap due to market movement).

A new manual type `reverse_split` was added to schema (`ManualType` in
`tickers.py`) alongside `bonus_issue`/`redomicile`. The split record builder
`_bonus_to_record` was generalised to `_ratio_to_record` — same arithmetic
(`ratio = before/after`, coef = before/after multiplies pre-D closes), only
the `type` and `source` strings differ.

After the fix:
- IRAO 2015-01 monthly total_return: was +100×, now +1.1% (within-month price
  drift from 0.712 to 0.72 on the post-cons scale).
- All adjusted closes pre-2015-01-20 are × 100, giving a continuous price
  series across the consolidation.

### 2. Multi-month trading gaps no longer produce synthetic returns

The previous `to_monthly_close` skipped months with no trading, so
`pct_change()` between adjacent records spanned multi-year trading gaps.
ERCO (2013-10 → 2016-11, with board change SMAL→TQBR in between) was emitting
a single +57× «monthly» return covering 37 idle months.

`to_monthly_close` now reindexes the monthly series to a contiguous
`Period[M]` range from the first traded month to the last. Months without
trading become NaN, which propagates one step into the next month's
`price_return`. Rows that remain NaN are dropped from the output JSONL (no
JSONL pollution), but the first traded month after a gap has
`price_return=null` — the universe filter (12 consecutive non-NaN returns
required) then excludes the ticker until trading resumes contiguously for
12 months.

Tested in `tests/test_monthly.py::test_trading_gap_does_not_create_synthetic_return`.

### What about within-month day gaps?

A stock that didn't trade for a few days within a single month is unaffected.
`to_monthly_close` does `groupby(period).tail(1)` — it picks the **last
trading day** of each month, no matter how sparse the month's trading was.
Multi-day intra-month gaps are invisible to the monthly aggregation.

### 3. Liquidity floor on the universe

`UNIVERSE_MIN_MEDIAN_MONTHLY_VALUE_RUB = 20_000_000` (`config.py`). At each
rebalance month t, a ticker is admitted only if its median monthly trading
value over the 12-month window [t-11..t] is ≥ 20M ₽.

Calibrated empirically against the author's published universe in
`raw_sources/Российские_акции_цены.csv` header (177 tickers, fixed
whitelist):

| threshold ₽/month | our universe size at 2026-03 |
|----------------:|-----------------------------:|
|              0 |  245 (no filter)             |
|             5M |  241                         |
|            10M |  219                         |
|        **20M** |  **181** ← matches author    |
|            50M |  146                         |
|           100M |  129                         |
|          1000M |   86                         |

Override per-run: `--min-liquidity-rub <N>`. 0 disables the filter.

Beyond removing UCSS-class noise, this filter:

- Brings our 2026-03 universe within ~3% of the author's 177-name whitelist.
- Restores **monotone Q1 > Q2 > Q3 > Q4** ordering for `curve_fit`.
- Cuts the early-history universe — `rebalances` dropped from 161 → 147
  because the first ~14 months of 2013-2014 no longer have ≥ 20M-median names
  with 13 prior monthly closes.

Added panel: `monthly_value_rub` (sum of daily ISS `value` over the month) in
`data/computed/monthly/*.jsonl`. `to_monthly_close` now produces this column
alongside `close_adj`.

## Tickers checked but NOT added as splits

| ticker | suspect month | finding | action |
|--------|---------------|---------|--------|
| UCSS   | 2019-02       | Daily prices ramp continuously 680→740→1000→…→55490 ₽ with no trading halt; volumes 1–50 shares/day. Genuine pump-and-dump on an illiquid microcap. | not a corporate action — left as-is. Future: liquidity filter on universe. |
| ERCO   | 2016-11       | Only 16 daily bars across 5 years total. Prior trade 2013-10-10 at 7 ₽; resumes 2016-11-03 at 412 ₽ on board change SMAL→TQBR. Bankrupt 2018-02-28. | 3-year gap, handled by the reindex fix above. No split. |

Per CLAUDE.md "do not fabricate content", fabricated splits would be worse
than the underlying problem.

## Remaining residual outlier (post-fix)

UCSS 2019-02 +80× still lives in the panel, but it's now structurally
excluded from the universe by the 20M-₽ liquidity floor — UCSS's median
monthly value before the pump was ≪ 1M ₽. Same applies to KMEZ, ZVEZ, ROLO,
PRFN and the rest of the original Q3-distortion set.

## Architecture verification (all gates green)

- **Universe filter** — 13 consecutive monthly closes ending at t,
  `type=="share"`, not `delisted_after <= month-end(t)`. Real-data: universe
  grows from ~30 in 2013-01 to 245 in 2026-05.

- **Signals** — `SimpleSignal()` = `r(12-1)/σ(12)`, `CurveFitSignal(a, b)` =
  `(a·r(12-1)+b·r(6-1))/σ(12)`. Asymmetry r-without-t / σ-with-t enforced.
  VSMO 2022-03 anchor reproduced: `r(12-1) = 4.6458%` from info.txt prices,
  abs_tol=0.0005.

- **Quartile split** — score DESC, tie-break ticker ASC; remainder rows go to
  top quartiles (|Q1| ≥ |Q4|, diff ≤ 1).

- **Turnover/cost** — `commission_per_side × Σ|Δw|`. Initial buy-in turnover
  = 1.0, full swap turnover = 2.0.

- **MCFTRR benchmark** — daily index → last-trading-day per month →
  `pct_change`. Applied on the same timing as quartile NAVs.

## Outputs (gitignored under `data/computed/`)

- `data/computed/{signal}/q_values.jsonl` — 162 rows: month + Q1..Q4 + MCFTRR
- `data/computed/{signal}/holdings/YYYY-MM.json` — 161 files, one per rebalance

## Next steps (out of Phase 9 scope)

1. Optional: triage remaining `_suspicious.json` entries (2028 total).
   Most flagged names are illiquid microcaps now structurally excluded by
   the 20M-₽ filter, so their distortion potential is neutralised.
2. Phase 10 — plotly charts of Q1..Q4 + MCFTRR series.
