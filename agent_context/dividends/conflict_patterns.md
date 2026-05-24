# Dividend source conflict patterns (task 012 phase 3 research)

Multi-agent research on 2026-05-16 across 5 high-conflict tickers (AKRN, GMKN,
CHMF, NLMK, AFLT) classified the cascade-merge conflicts into 3 buckets.
This document records the patterns so future audits don't re-investigate.

## Bucket 1 — Cascade-priority handles correctly (ISS canonical)

External feeds (Yahoo, tbank) report a DIFFERENT but RELATED number for the
same payout. ISS gives the legally-declared per-share gross amount; external
gives a derived/adjusted figure that does not belong in a momentum-formula
dataset using raw prices. Cascade priority drops the external record — no
action needed.

### 1A — Quasi-treasury gross-up
- **Yahoo amount = ISS / (1 − treasury_fraction)**
- AKRN exemplar: ratio 1.1027 = 1/0.9069 across 18 records 2014-2022.
  Acron has ~9% quasi-treasury via Dorogobuzh subsidiaries (Interfax cite
  8.25% for one consolidation tranche). Yahoo redistributes declared cash
  to non-treasury free-float shares as "effective per-share to outside
  shareholder".
- **Likely also affects**: SNGS (Surgut, ~75% treasury), TATN (Tatneft,
  ~16%), MTSS (MTS, ~6% bought-back), SFTL, any issuer with long-standing
  buy-back hold.
- **Action**: trust ISS (legally-declared per share). Yahoo's "per outside
  share" is wrong granularity for a (price-per-share, dividend-per-share)
  pair used in total-return calc.

### 1B — Capital-reduction mis-classification as split
- **Yahoo back-scales pre-event dividends by share-count ratio**
- GMKN exemplar: ratio 1.0352 = 158,245,476 / 152,863,397 across 16 records
  2013-2020. Norilsk cancelled 5.38M quasi-treasury shares on 2021-10-06
  (EGM 2021-08-20). Yahoo data pipeline (and possibly Refinitiv/S&P
  upstream) treats capital reduction like a reverse split → back-scales
  historical per-share cash dividends. This is incorrect: cash dividends
  are nominal payments to then-existing shareholders, NOT per-share-economic
  rights that re-spread when supply contracts.
- **Action**: do NOT add capital reductions to `data/splits/`. ISS canonical.
- **GitHub reference**: quantmod issue #253 documents this Yahoo bug class.

### 1C — Rights-issue / SPO theoretical-ex-rights price adjustment
- **Yahoo back-scales by TERP/cum-price ratio**
- AFLT exemplar: ratio 0.816 across 4 records 2014-2019. Aeroflot SPO
  2020-10 placed 1.334B new shares at 60 RUB vs ~73.5 RUB market. Yahoo
  applies adjustment factor to historic dividends as if the SPO were a
  stock dividend.
- **Not a split**, factor is irrational (not before/after integer ratio).
- **Action**: trust ISS. Document the SPO event in audit log, don't add to
  `data/splits/`.

### 1D — Net-of-tax
- **Yahoo amount = ISS × 0.87** (13% Russian resident WHT) or **× 0.85**
  (15% non-resident WHT)
- BELU exemplar: ratio 0.875 (some sources mis-round 0.87 to 0.875).
- **Action**: trust ISS gross.

### 1E — Rounding (within ±5%)
- External feed has display-level rounding (smart-lab/tbank round-to-2-dec).
- ISS gives full precision. RASP, SVCB exemplars.
- **Action**: trust ISS.

## Bucket 2 — Multi-tranche schema gap (AUGMENT needed)

External (especially Yahoo) reports a SUM of multiple same-day tranches.
ISS captures only ONE of the tranches. The other tranche(s) are missing
from production data entirely. AUGMENT from dohod's per-tranche table.

- **CHMF exemplar**: prior-FY-final + new-Q1-interim on same registry date
  for 8 of 11 multi-tranche June months 2014-2024.
- **NLMK exemplar**: same pattern, 3-4 affected years.
- **AKRN 2025-06-09 exemplar**: 427 (FY2024 final) + 107 (retained earnings)
  on same registry date.
- **Likely also affects**: MAGN, PHOR historically (per CHMF agent's
  hypothesis), PLZL.
- **Action**: add `_conflicts_resolved.json` entry with `action="augment"`,
  `add={amount, currency, source: "skill_fill_dohod"}`, reason cite dohod
  per-tranche table.

## Bucket 2b — Tranche-aggregation duplicate (cascade auto-handles since 2026-05-16)

External feed reports a SUM of tranches we store individually (or vice versa:
ISS aggregates, external splits). Pre-2026-05-16 this surfaced as ymconflict;
now `classify_bucket` in `src/momentum/dividends/merge.py` detects when
`sum(unmatched_proposed) ≈ sum(unmatched_existing)` within 1% and drops the
proposed as duplicate.

- **AQUA exemplar**: existing [4, 5] tranches, tbank reports [9] sum.
- **TRNFP exemplar**: existing [7578.27] ISS aggregation, tbank reports
  [4308.81, 3269.46] tranches.
- **VRSB / CHMF exemplar**: resolved sums vs tbank per-tranche.
- **Action**: none — auto-handled by cascade since 2026-05-16. Don't add to
  `_conflicts_resolved.json`.
- **Caveat**: drops the tranche granularity that external feed offers. If you
  WANT per-tranche records, add `augment` entries manually with dohod sources.

## Not-a-bucket: TNS Energo pref==common pattern (charter-correct, falsified hypothesis)

Earlier spot-check noticed `MISBP/RTSBP/VRSBP/STSBP` ISS pref values equal
common-ticker values on most historical shared dates. Initial hypothesis:
"ISS cross-contamination — returning common-class on pref ticker." **This
hypothesis was independently falsified** (2026-05-16 wave 4 charter audit):

- All four TNS Energo regional subsidiaries share the same Type-A pref
  charter clause: "10% of prior-year net profit / pref count, **with
  mandatory raise-to-common if the formula yields less than common
  dividend**".
- `pref == common` is the **expected** outcome when net-profit-formula
  payout per pref is less than the per-common payout.
- The 2023 anomalies (MISBP=3.80 vs MISB=0.49; RTSBP=0.0477 vs RTSB=0.0315)
  are charter-formula payouts in years when net profit was healthy and
  common payouts were small.

**Action**: do nothing for pure pref==common rows on TNS Energo tickers —
this is charter-correct. Only intervene if a per-AGM primary source
disagrees with the stored value.

The MISBP 2022-07-13 case that initially triggered this hypothesis: the
RBC reference to "MISBP = 1.92" was for the **2021-FY-final** AGM decision
also paid on 2022-07-13 (1.92 EQ both classes), separate from the
**1Q2022** decision (0.60 EQ both classes) which corresponds to the
existing 0.566 record. Resolution: augment +1.92 to both MISB and MISBP
for the missing FY2021 tranche; existing 1Q records remain canonical.

## Bucket 3 — Already resolved by split-aware adjust

External pre-split records, after multiplying by split factor, match ISS.
Cascade adds these as clean (non-conflict) records, GAIN data ISS lacks.

- VTBR (1:5000 reverse 2024-07-15): 9 pre-2017 records added to ISS-data.
- GMKN (1:100 forward 2024-04-08): post-adjust the 1.035 residual remains
  (Bucket 1B), but rest of pre-split data aligns.
- GEMA (1:10 forward 2024-02-08), PLZL (1:10 forward 2025-03-27), TRNFP
  (1:100 forward 2024-02-21), KOGK, URKZ, IRAO, ROLO, T.
- **Action**: handled automatically by `cascade_merge_dividends.py` split
  adjustment, no manual entries needed.

## Authoritative-source hierarchy (when augmenting)

1. **dohod.ru/ik/analytics/dividend/{ticker}** — most reliable for per-tranche
  history with fiscal-period attribution.
2. **smart-lab.ru/q/{TICKER}/dividend/** — agreement with dohod is strong
  signal; embedded `aYearSeries` gives annual totals only.
3. **Issuer IR page** (severstal.com, nlmk.com, nornickel.com, akron.ru) —
  primary press releases for AGM/board decisions.
4. **RIA/Forbes/Vedomosti** — corroborate via news reporting per-event.
5. e-disclosure.ru — official AGM minutes (heavy HTML parsing).

## Audit-log references

- AKRN: agent verified 18 records via dohod + Vedomosti + Forbes (Acron 2017,
  2025-06).
- GMKN: 16 records verified via Nornickel annual reports + RIA + smart-lab.
- CHMF: 8 multi-tranche years verified via dohod + smart-lab + Severstal IR
  press release for 2014-06-23 paired AGM.
- NLMK: 3 confirmed (2016/2017/2018), 2015-06 ambiguous (skip).
- AFLT: 4 records verified via Aeroflot AR + dohod + smart-lab + RBC.
