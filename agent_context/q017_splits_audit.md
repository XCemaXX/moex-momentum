# Q017 — Split-adjustment audit: can it explain Q1 < Q2 in 2013-2020?

## Question

The momentum backtest forms quartile portfolios (Q1 top momentum ... Q4 bottom).
In 2013-2020 Q1 underperforms Q2. **Hypothesis (low priority, expected to be
ruled out):** a mis-applied or spurious stock-split adjustment inflates a
ticker's trailing 12-month return, pushing it into Q1 right before it reverts,
dragging Q1 down.

This audit tests that concretely against the data.

## Inputs examined

- `data/splits/*.csv` — 12 split-event files (brief said 11; **VTBR is also
  present**).
- `data/splits/_acked.json` — **empty (`[]`)**. No split is formally
  acknowledged/confirmed in this file.
- `data/splits/_suspicious.json` — 2028 detector rows, `reason =
  abs_return_above_threshold`. These are daily-return outliers, **not** a
  confirmed-split list. The bulk are ~±0.40 values, i.e. MOEX daily price-limit
  moves and genuine crisis days, not splits. Not used as ground truth here.
- `data/momentum/monthly/{TICKER}.csv` — per-ticker monthly series; `close_adj`
  is split- and dividend-adjusted.
- `data/momentum/curve_fit/holdings/*.json` — 160 monthly Q1..Q4 holdings files,
  range 2013-01 .. 2026-04.

## 1. Split events and 2013-2020 flag

| Ticker | Date       | before:after | Type           | Source                | In 2013-2020? |
|--------|------------|--------------|----------------|-----------------------|---------------|
| BELU   | 2024-08-20 | 1:8          | bonus_issue    | manual_bonus_issue    | no            |
| GEMA   | 2024-02-08 | 1:10         | forward        | moex_iss              | no            |
| GMKN   | 2024-04-08 | 1:100        | forward        | moex_iss              | no            |
| **IRAO** | **2015-01-20** | **100:1** | **reverse_split** | **manual_reverse_split** | **YES** |
| KOGK   | 2025-08-15 | 1:100        | forward        | moex_iss              | no            |
| PLZL   | 2025-03-27 | 1:10         | forward        | moex_iss              | no            |
| ROLO   | 2023-01-18 | 1:10         | forward        | moex_iss              | no            |
| T      | 2026-04-17 | 1:10         | forward        | moex_iss              | no            |
| TRNFP  | 2024-02-21 | 1:100        | forward        | moex_iss              | no            |
| URKZ   | 2025-08-05 | 1:100        | forward        | moex_iss              | no            |
| VTBR   | 2024-07-15 | 5000:1       | reverse        | moex_iss              | no            |

**Exactly one** split event falls in the 2013-2020 window: **IRAO,
2015-01-20, a 100:1 reverse split (`manual_reverse_split`).** Every other split
post-dates the window (earliest of the rest is ROLO 2023-01).

## 2. Acknowledged vs detected

`_acked.json` is empty, so no event is "confirmed" via that mechanism. The
`source` column distinguishes provenance: `moex_iss` (pulled from the exchange
ISS endpoint) vs the three `manual_*` rows (BELU, IRAO). The IRAO event is
manual, which raises the prior that it could be wrong — examined directly below.

## 3. IRAO 2015-01-20 — is there a split artifact?

Direct inspection of `data/momentum/monthly/IRAO.csv`:

```
month     close_adj   total_return
2014-11   0.8949      -0.0668
2014-12   0.7120      -0.2044
2015-01   0.7200      +0.0112   <- split month (2015-01-20)
2015-02   0.9188      +0.2761
2015-03   1.0999      +0.1971
```

- The series is **perfectly continuous** through the split date. No 100x jump,
  no discontinuity.
- IRAO `close_adj` ranges **0.712 .. 5.8 over its entire history** (2008-10 ..
  2026-04). It has always been a sub-6-RUB stock. A real 100:1 reverse split
  would have moved the raw price to the ~70-90 RUB range either before
  (unadjusted) or after (mis-adjusted) — neither appears anywhere in the series.
- IRAO has **zero** months with `|total_return| > 0.5` across its full history.

**Conclusion on the event itself:** the "2015-01-20 100:1 reverse split" is
spurious / not reflected in IRAO's actual trading. It was either never applied
(because the underlying data was already a continuous sub-2-RUB series) or the
event is simply wrong. Either way, **it produced no artifact in the momentum
inputs.** There is nothing for the hypothesis to bite on.

## 4. Cross-reference: split-tickers in Q1 (2013-2020) and subsequent returns

Scanned all 96 in-window holdings files for the 11/12 split-tickers in Q1, then
read the realized next-month `total_return`.

Findings:

- **IRAO never appears in Q1 in the months immediately after its split.** Its
  first Q1 appearance is **2015-07** (six months later), and its run of Q1
  membership (2015-07 .. 2017-09, then sporadically 2018-2020) shows mild
  returns: e.g. next-month tr of +0.004 (2015-08), +0.157 (2016-03, a real
  recovery), -0.054 (2020-03). **No large negative reversion** follows any IRAO
  Q1 entry. There is no "phantom momentum then crash" pattern.
- The split-tickers that *do* sit in Q1 through 2013-2020 are **TRNFP, GMKN,
  PLZL, VTBR** — but their splits are all in 2024-2025, **outside** the window,
  so their in-window prices are unadjusted-and-correct. Their Q1-period returns
  are ordinary (mix of small + and -).
- In-window months with `|total_return| > 0.5` for any split-ticker:
  - GMKN 2015-01 = **+0.437** — genuine. `close_adj` 80.8 -> 116.1, no split
    (GMKN's only split is 2024-04). This is the post-ruble-devaluation rally in
    export-heavy Nornickel.
  - PLZL 2015-04 = **+0.520** — genuine. PLZL's split is 2025-03; this is the
    gold/FX-driven move. Not an artifact.
  - IRAO, TRNFP, VTBR: **none**.

None of these spikes is a split artifact, and none coincides with a split date.

## 5. Verdict

**RULED OUT.** Split-adjustment is not a plausible contributor to Q1 < Q2 in
2013-2020, on the numbers:

1. Only one split event (IRAO 2015-01-20) falls in the window at all.
2. That event left **no trace** in IRAO's monthly series — the price is
   continuous and stays sub-6-RUB throughout; the manual 100:1 reverse looks
   spurious and was not applied to the data.
3. IRAO did not enter Q1 around its split (first Q1 entry is +6 months later)
   and never suffered a split-linked negative reversion.
4. The only large in-window monthly moves among split-tickers (GMKN +44%
   2015-01, PLZL +52% 2015-04) are genuine fundamental/FX moves with no split in
   the window.

The mechanism the hypothesis requires — a spurious split inflating trailing
return, forcing Q1 entry, then reverting — **does not occur in the data**. Look
elsewhere for the Q1 < Q2 driver.

### Caveats / limits

- This relies on the 12 split CSVs being the complete split universe. If a
  real in-window split is *missing* from those files, this audit would not catch
  it. The `_suspicious.json` detector flagged many in-window ±0.40 daily moves,
  but those match MOEX daily price limits and crisis days, not splits — none was
  confirmed as a split here. A separate sweep for *unrecorded* splits is out of
  scope for this task.
- The analysis uses monthly granularity for the artifact check. A within-month
  split fully reversed inside the same month could be masked, but a 100:1 / 5000:1
  scale event cannot be reversed within a month, so the monthly view is adequate
  for the recorded events.
