# Per-ticker dividend conflict verdicts (task 012 phase 3)

Append-only log of agent research for ymconflict candidates from
`scripts/cascade_merge_dividends.py` dry-run. Each entry records: ticker(s),
agent run date, bucket assignment per
[dividend_conflict_patterns.md](dividend_conflict_patterns.md), action taken
(if any), and authoritative source.

## Bucket legend

- **1A** — quasi-treasury gross-up (Yahoo / (1-treasury_fraction))
- **1B** — capital reduction mis-classified as split
- **1C** — SPO/rights TERP back-adjustment
- **1D** — net-of-tax
- **1E** — rounding / display precision
- **2** — multi-tranche schema gap (AUGMENT needed)
- **3** — already resolved by split-aware adjust
- **NEEDS_INVESTIGATION** — agent couldn't pin down, manual TODO

## Verdicts

### 2026-05-16 wave 1 (5 agents, ratio-pattern leaders)

| Ticker | Conflicts | Bucket | Action taken | Source |
|---|---:|---|---|---|
| AKRN | 19 | 1A (18) + 2 (1 — 2025-06 already augmented) | None (cascade OK) | dohod + Vedomosti + Forbes; Acron quasi-treasury ~9% via Dorogobuzh; 1.1027 = 1/0.9069 |
| GMKN | 16 | 1B | None (cascade OK) | Nornickel AR 2017/2022 + RIA + smart-lab; 1.0352 = 158.245M / 152.863M from Oct-2021 treasury cancellation |
| CHMF | 15 → 7 residual | 2 (8 multi-tranche augments applied) | 8 augments in `_conflicts_resolved.json` | dohod per-tranche + Severstal IR press release |
| NLMK | 8 → 5 residual | 2 (3 multi-tranche augments applied) | 3 augments | NLMK press release + smart-lab + tbank |
| AFLT | 4 | 1C | None | Aeroflot AR 2019 + dohod + smart-lab + RBC; 0.816 ≈ TERP for 2020 SPO |

### 2026-05-16 wave 1b (5 agents, residual-volume tickers)

| Ticker | Conflicts | Bucket | Action taken | Source |
|---|---:|---|---|---|
| PLZL | 9 | tbank-bug | Add to `_external_blacklist.json` (exclude tbank) | Polyus IR + dohod + Forbes; tbank ×10 bug (likely double-applying 2025-03 split) |
| BELU | 11 | 1F (Yahoo bonus-adjust bug, 7/8 instead of 1/8) | None (cascade OK) | Forbes + RBC + Novabev IR; bonus 1:8 confirmed but Yahoo's adjustment math wrong |
| SVCB | 7 | 1E (IPO retro-norm) | None | smart-lab + RBC + Vedomosti; ISS retro-normalized to post-IPO ~20B shares |
| RASP | 6 | 1B (capital-reduction mis-class) | None | dohod + smart-lab + finanz.ru; 1.0264 ≈ 17M cancelled / 665.7M float |
| HYDR | 4 | ISS-WRONG (2-decimal truncation) | 4 replaces (0.01→0.013588 etc) | dohod + smart-lab + Yahoo all agree on 5-dec precision |

### 2026-05-16 wave 2 (5 agents, batched medium/low-volume)

| Ticker | Conflicts | Bucket | Action taken | Source |
|---|---:|---|---|---|
| AQUA | 3 | 2 | 2 augments | dohod + smart-lab; Q1 missing |
| LKOH | 3 | 2 (2022-12 multi-tranche) + 1C (2013) | 1 augment (2022-12-21 +256) | dohod + smart-lab; 9M-2022 interim 256 paired with FY2021 537 |
| MAGN | 3 | 2 (2021-06) + 1 Yahoo data error (2016) | 1 augment (2021-06-17 +1.795) | dohod + smart-lab; Q1 2021 interim |
| MSNG | 3 | ISS-WRONG (2-dec truncation) | 3 replaces | dohod + smart-lab |
| MSRS | 3 | ISS-WRONG (truncation) | 3 replaces | dohod + smart-lab |
| NMTP | 3 | ISS-WRONG (truncation) | 3 replaces | dohod + smart-lab |
| IRAO | 2 | ISS-WRONG (truncation) | 2 replaces | dohod + smart-lab |
| FEES | 1 | ISS-WRONG (truncation 0.01→0.0133) | 1 replace | dohod |
| MRKV | 1 | ISS-WRONG (truncation 0.01→0.007044) | 1 replace | dohod + Yahoo exact match |
| UPRO | 2 | 2 (already augmented in production via prior task-005 dohod fills) | None — already in data | dohod |
| MISB | 1 | 2 (ambiguous tranche breakdown) | **FLAG** — needs manual verify | smart-lab incomplete |
| MISBP | 1 | 2 (same) | **FLAG** | — |
| RTSB | 1 | 2 (ambiguous) | **FLAG** | smart-lab breakdown doesn't match ISS |
| RTSBP | 1 | 2 (same) | **FLAG** | — |
| MRSB | 1 | 2 | 1 augment | smart-lab |
| MRKU | 1 | 2 (already augmented in production) | None — already in data | dohod + iss live |
| EUTR | 2 | 2 | 2 augments | smart-lab tranches |
| TGKN | 1 | 2 | 1 augment | dohod |
| UDMN | 1 | tbank-bug (year-shift) | Add to blacklist (exclude tbank) | dohod + IR |
| RTKM | 1 | yahoo-bug (×5, possibly ADR ratio) | Add to blacklist (exclude yahoo) | dohod + smart-lab + Rostelecom IR |
| HNFG | 1 | 2 | 1 augment | tbank sum |
| NKHP | 1 | yahoo-wrong | Add to blacklist (exclude yahoo) | Forbes article on AGM 22.19 |
| ABRD | 1 | 2 (was wrongly blacklisted) | REMOVE from blacklist + 1 augment | dohod sum 6.33 = 0.19 + 6.14 |
| VRSB | 2 | ISS-WRONG (under-reported, captured 1 of 3 tranches) | 1 replace 3.94→14.69 | smart-lab + investing.com |
| VRSBP | 1 | ISS-WRONG (same as VRSB) | 1 replace | investing.com confirms pref=common per TNS charter |
| KBSB | 1 | ISS-WRONG (multi-tranche TNS-energo group 2022) | 1 replace 13.99→18.19 | smart-lab |
| PIKK | 2 | 2 (2018 cascade OK; 2021 already augmented) | None | dohod + smart-lab |
| POSI | 1 | 2 | 1 augment | dohod + smart-lab sum 51.89 |
| SVAV | 2 | 1A | None | dohod confirms ISS |
| GCHE | 1 | 1B (Yahoo aggregated ordinary + special) | None | dohod |
| IRKT | 1 | 1F (Yahoo wrong) | None | smart-lab confirms 1.14 |
| MRKY | 1 | 1F (Yahoo wrong) | None | dohod confirms ISS exactly |
| AVAN | 1 | 2 | 1 augment +7.54 | dohod + rbc; 31.66 special + 7.54 annual = 39.20 |
| CNTL | 1 | 1E (rounding) | None | smart-lab confirms ISS 0.034 |
| CNTLP | 1 | 1E (rounding) | None | smart-lab |
| RDRB | 2 | 1A (1C variant) | None | investing.com confirms ISS 9.85; smart-lab/dohod history truncates at 2020 |

### 2026-05-16 wave 3 (Agent C — residual post-fix audit)

Cascade gap discovered: `_amount_close` check didn't detect tranche-aggregation
in either direction (single ISS aggregated value vs N external tranches, or N
internal tranches vs single external sum). False-positive ymconflicts on TRNFP,
AQUA, VRSB, NKHP-tbank.

| Ticker | Issue | Action taken |
|---|---|---|
| TRNFP | ISS 7578.27 aggregates 2018-07-10 tranches (4308.81 FY2017 final + 3269.46 9M2017); tbank stores per-tranche | Structural fix in cascade (see below) — auto-resolved |
| NKHP | Blacklist excluded only `yahoo`, but tbank also carries wrong 30.43 vs ISS 22.19 | Extended blacklist to `["yahoo","tbank"]` |
| AQUA | Existing [4,5] + [10,10] tranches; tbank reports sums [9, 20] | Structural fix auto-resolved |
| VRSB / VRSBP / KBSB | Resolved sums vs tbank per-tranche reports | Structural fix auto-resolved |

**Structural fix**: added `classify_bucket` in `src/momentum/dividends/merge.py`
with 3-phase logic (pairwise → sum-aggregation → conflict). cascade_merge_dividends
uses it. Tests in `tests/test_dividends_classify.py` (10 cases).
Effect: ymconflicts 111 → 83 (-28); CHMF 7→0, TRNFP 2→0, VRSB 2→0, AQUA 2→0,
UPRO 2→0, NLMK 5→2, AKRN 19→18, LKOH/MAGN/PIKK 2→1.

### 2026-05-16 wave 4 (Agent A + TNS Energo charter audit — partial retraction)

Initial wave-4 entries (MISBP REPLACE, RTSB×2 + RTSBP×2 augments, MISB +0.0377)
were **retracted** after independent charter audit falsified the
"pref cross-contamination" hypothesis. Final state:

| Ticker | Conflicts | Bucket | Action taken | Source |
|---|---:|---|---|---|
| MISB | 1 | 2 (multi-AGM same-day: 1Q2022 + FY2021-final both on 2022-07-13) | 1 augment +1.92 (FY2021 tranche) | RBC quote/ticker/59336 + TNS Energo Type-A pref charter |
| MISBP | 1 | 2 (same multi-AGM pattern; both classes EQ per charter) | 1 augment +1.92 (FY2021 tranche, EQ both classes) | RBC + smart-lab + charter |
| RTSB | 1 | **deferred (wave 5 follow-up agent)** | none — agent A and charter agent disagree on tranche count (3 vs 2), need primary e-disclosure | — |
| RTSBP | 1 | deferred (wave 5 follow-up agent) | none | — |

**Charter audit finding** (closes the cross-contamination hypothesis):
All four TNS Energo regionals (Mari El, Rostov, Voronezh, Stavropol) share
identical Type-A pref clause: "10% net profit / pref count, with mandatory
raise-to-common if formula < common payout." So `pref == common` rows
(MISBP 5/6, RTSBP 4/5, VRSBP 6/6, STSBP 1/1 historical) are
**charter-correct, not contamination**. No backfill needed.

### 2026-05-16 wave 5 (4 verification agents + ignore mechanism)

Goal: drive `ymconflicts` from 82 to near-zero by independently verifying each
remaining forever-conflict and silencing via new `action: "ignore"` mechanism
in `_conflicts_resolved.json`.

**Verification (4 parallel agents)**:
- V1 AKRN/GMKN: both CONFIRMED IGNORE. Ratios degenerate to 5-6 decimals
  (FP-noise stdev). Mechanism math reconciles to primary share-count data.
- V2 BELU/RASP/AFLT: all 3 CONFIRMED. Yahoo 7/8 bonus bug (Novabev 7-for-1
  bonus 2024), RASP 1.0257 cap-reduction (Evraz buyback 2022), AFLT 0.8158
  TERP (Aeroflot SPO Oct 2020).
- V3 SVCB/NLMK/LKOH/MAGN/PIKK: 4 CONFIRMED + NLMK 2015-06 NEEDS REVISIT.
  Reclassifications:
  - SVCB was "Bucket 1E IPO retro-norm" → actually "tbank 2-decimal
    truncation". Same outcome.
  - LKOH 2013 was "Bucket 1C TERP" → actually generic Yahoo data error (no
    Lukoil SPO in 2013).
- V4 RDRB/SVAV/CNTL/CNTLP/GCHE/IRKT/MRKY/TGKN/VRSBP: all 9 CONFIRMED IGNORE.
  + side-note: GCHE 2021-04-07 13.58 RUB second tranche missing from prod.

**Bug investigation (separate agent)**:
- GCHE 2021-04-05: augment +13.58 RUB (FY2019 undistributed profit, paired
  with FY2020 final 120.42 on same registry). Confirmed via TASS, finanz.ru,
  smart-lab, dohod (sum 134.00).
- NLMK 2015-06-16: augment +1.56 RUB (FY2014 final, paired with Q1-2015
  interim 1.64 on same registry). Confirmed via ProFinance, metalinfo, dohod
  per-tranche table. Yahoo sum 3.20 corroborates.

**Mechanism added** (`src/momentum/dividends/conflicts.py::should_ignore_conflict`):
- New `action: "ignore"` in `CONFLICT_ACTIONS`. Does NOT modify JSONL — only
  silences ymconflict-flagging in cascade for verified Bucket-1 patterns.
- Match by `ticker` (required), `match.source` (optional), and either
  `registry_close` (specific) or `applies_to_ym_pattern` ("*" or "YYYY-MM").
- 20 ignore entries added covering 24 forever-conflict tickers.
- 9 unit tests in `tests/test_dividends_ignore.py`. All 267 tests pass.

**Result**: dry-run `ymconflicts=82 → 4` (NLMK×2 self-resolve after apply,
RTSB/RTSBP deferred to wave 5 follow-up agent). `ignored=78`.

### Open / deferred

- **Sub-0.10 ISS truncation sweep** (Agent B): originally 14 suspect rows.
  Yahoo cache cross-check (2026-05-16) confirmed **5 as REAL** (not bugs):
  JNOSP 2018-07-09 + 2019-07-12 (`0.01` exact, charter-min), MTLRP 2014-07-11
  + 2015-07-11 + 2016-07-11 (`0.05` exact, preferred 10%-par charter coupon).
  Remaining 9 unverifiable suspects (OGK2×4, MRKH×3, VTBR 2016-12-26, OGK4
  2017-07-04) have no Yahoo + no tbank cache coverage; dohod/smart-lab 404.
  Per project policy: don't fabricate. Acceptable noise; impact on
  total-return at price 1-2 RUB is sub-noise. **0 confirmed bugs.**
- **RTSB / RTSBP 2022-07-20 tranche structure**: wave 5 follow-up agent
  running. Earlier agents disagreed on decomposition (3 tranches vs 2);
  need primary AGM minutes from e-disclosure.ru.
- **Legacy `skill_fill_dohod` audit** (2026-05-16): re-checked 196/213
  records across 25 tickers. **0 flagged**. CHMF/NLMK/AQUA/UPRO/POSI
  multi-tranche backfills correctly captured the missing tranches on top
  of existing ISS records. 4 records (KBSB/VRSB/VRSBP/MRSB) unverifiable
  because dohod ticker pages now 404 — retained as-is.
