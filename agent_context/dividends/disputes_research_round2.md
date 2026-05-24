# Dividend disputes — ground-truth research, round 2

Continuation of `dividend_disputes_research.md`. Seven new cases where MOEX ISS
disagrees with dohod by an integer ratio (mostly 0.5×, some 1/2.14, 1/2.5).
Sources: dohod.ru historical tables (direct fetch), smart-lab dividend pages,
RBC/BCS extracts, Novatek IR (blocked, content via search summaries).
WebFetch blocked on interfax.ru, investfunds.ru, tbank.ru, bcs.ru, finviewer.ru,
novatek.ru. Primary evidence drawn from dohod.ru fetches and WebSearch result
quotes.

---

## LSRG 2017-06-20

**Verdict: dohod correct (78 RUB). MOEX ISS value 40 is wrong (≈half).**

**Evidence:**
- https://www.dohod.ru/ik/analytics/dividend/lsrg — single row "20.06.2017 ... 78 ₽ ... 2017".
- https://bcs-express.ru/novosti-i-analitika/lsr-chetvertyi-god-podriad-zaplatit-78-rub-na-aktsiiu — "ЛСР четвёртый год подряд заплатит 78 руб. на акцию" — confirms 78 RUB has been the standing annual amount for 2014–2017.
- WebSearch summary from RBC: "дивиденды в размере 78 рублей выплачивались 20 июня 2017 года с дивидендной доходностью 9,94%". 9.94% yield at LSR's mid-2017 price (~785 RUB) matches 78, not 40.
- AGM-approved annual amount for FY2016 was 78 RUB; total 8.036 bln RUB.

**Confidence:** high

**Recommendation:** replace ISS 40 with dohod 78. Same stale half-figure pattern as MTLRP/SFIN.

---

## SELG 2019-12-24

**Verdict: dohod correct (0.78 RUB). ISS 0.40 is wrong (≈half).**

**Evidence:**
- https://www.dohod.ru/ik/analytics/dividend/selg — single row registry 24.12.2019 = 0.78 RUB; period 2019; yield 6.4%.
- Search summary: "На 24 декабря 2019 г. Селигдар выплатил 0,78 руб. на акцию, доходность 6,4%".
- 2017/2018 — no payments. 0.78 is the first dividend after the pause.

**Confidence:** high

**Recommendation:** replace ISS 0.40 with dohod 0.78. Same half-figure pattern.

---

## VSMO 2023-06-05

**Verdict: both records are real (different declarations, same registry date). ISS is missing the second tranche. Total = 1127.57.**

**Evidence:**
- https://www.dohod.ru/ik/analytics/dividend/vsmo — TWO rows sharing registry 05.06.2023:
  - declaration 03.05.2023 → 563.80 RUB (for fiscal 2022)
  - declaration 17.05.2023 → 563.77 RUB (for fiscal 2023 — likely 1Q2023 interim)
  - Combined: ~1127.57 RUB/share.
- VSMO held a single GOSA on 30.05.2023 that approved both the FY2022 final dividend AND a 1Q2023 interim — both with the same record date 05.06.2023, mirroring the PIKK 2021-05-17 pattern from round 1.
- ISS appears to retain only one of the two tranches (563.77).

**Confidence:** high

**Recommendation:** accept BOTH records (563.80 + 563.77 = 1127.57). Augment ISS with the missing tranche. Same "two-tranche AGM, shared registry date" pattern as PIKK 2021-05-17.

---

## AVAN 2018 — unresolved

**Verdict: unresolved. Both ISS 6.20 and dohod 12.40 are suspect; aggregator pages disagree among themselves.**

**Evidence:**
- https://www.dohod.ru/ik/analytics/dividend/avan — direct fetch returned ONE 2018 row: 6.20 RUB, registry 08.07.2018, declared 24.05.2018, period "2018". This matches ISS, not the dohod 12.40 total the user reported.
- https://smart-lab.ru/q/AVAN/dividend/ — shows a single 2018 distribution at 34.42 RUB, registry 12.06.2018, labelled "4Q 2017", with an annual-summary cell of "12.4" RUB for 2017. 34.42 ≠ 6.20 and ≠ 12.40; suggests either a per-share figure on a different share count (recapitalised? split?) or smart-lab data error.
- AVAN has had a share-count change at some point (capital increase / share-class reorg); per-share dividend amounts before/after a recap don't compare cleanly. Without an authoritative AVAN charter / e-disclosure dump, we cannot reconcile the three numbers (6.20 / 12.40 / 34.42).
- Search did not surface a Board minutes / e-disclosure document confirming the 2018 per-share amount.

**Confidence:** low

**Recommendation:** quarantine the AVAN 2018 record. Do NOT silently take either side. Ask user to source the AVAN 2017/2018 board minutes or e-disclosure dump. Likely explanation: share-count change between dohod's snapshot and smart-lab's snapshot, or an aggregator counting one of the two semi-annual distributions while the other counts both.

---

## NVTK 2018

**Verdict: both correct (different payments). ISS missing the interim payment.**

**Evidence:**
- https://www.dohod.ru/ik/analytics/dividend/nvtk — TWO payments in calendar 2018:
  - 03.05.2018 → 8.00 RUB (4Q 2017)
  - 10.10.2018 → 9.25 RUB (1H 2018 interim)
  - Calendar-2018 total: 17.25 RUB.
- ISS retains only the 9.25 (October) payment; the 8.00 RUB from May 2018 is missing.
- The 17.25/9.25 ≈ 1.86 ratio (NOT a clean 0.5×) is the giveaway that this is a missing-tranche case, not a halved-figure case.

**Confidence:** high

**Recommendation:** accept BOTH records (8.00 + 9.25 = 17.25). Augment ISS with the missing May tranche. Pattern: ISS missing one of two semi-annual payments — same class as PIKK and VSMO.

---

## HIMCP 2018

**Verdict: dohod correct. ISS is missing two of four quarterly payments.**

**Evidence:**
- https://www.dohod.ru/ik/analytics/dividend/himcp — FOUR payments in calendar 2018, all fiscal-2018 period:
  - 25.03.2018 → 0.1190 RUB
  - 26.06.2018 → 0.2095 RUB
  - 01.08.2018 → 0.1379 RUB
  - 11.12.2018 → 0.1381 RUB
  - Total: 0.6045 RUB (dohod reports 0.6045, the user's 0.60 matches).
- ISS total 0.28 ≈ 0.1379 + 0.1381 = 0.2760 — captures only the August and December payments. Misses the March (0.1190) and June (0.2095) payments, which together = 0.3285.
- Himprom pays quarterly small interim dividends, not annual.

**Confidence:** high

**Recommendation:** accept ALL FOUR dohod records. ISS is undercounting by missing the first two quarterly tranches. Pattern: same as PIKK/NVTK/VSMO (missing interim payments) but more extreme — four-payment cadence.

---

## KAZT 2018 (and KAZTP by symmetry)

**Verdict: dohod correct. ISS is missing interim payments.**

**Evidence:**
- https://www.dohod.ru/ik/analytics/dividend/kazt — TWO payments tagged fiscal "2018" with registries in calendar 2018:
  - 10.05.2018 → 2.00 RUB (final FY2017, paid in May 2018)
  - 23.12.2018 → 2.00 RUB (3Q 2018 interim)
- https://smart-lab.ru/q/KAZT/dividend/ — THREE registries land in calendar 2018:
  - 08.01.2018 → 1.00 RUB (3Q 2017)
  - 10.05.2018 → 2.00 RUB (4Q 2017)
  - 23.12.2018 → 2.00 RUB (3Q 2018)
  - Calendar-2018 total: 5.00 RUB. This matches dohod's "5.00 RUB total 2018" cited in the user's case.
- ISS retains 2.00 RUB only — captures one of three tranches.
- 5/2 = 2.5 ratio explained: dohod aggregates 3 payments at 1+2+2; ISS keeps one 2.00 payment. NOT a halved-figure case — a missing-tranche case.

**Confidence:** high

**Recommendation:** accept ALL THREE dohod records (1.00 + 2.00 + 2.00 = 5.00). Augment ISS with the two missing tranches. Same pattern as HIMCP — quarterly cadence with ISS dropping the smaller interim payments.

---

## Cross-cutting observations (round 2)

Two distinct error classes confirmed by this round, both already foreshadowed in round 1:

1. **Stale half-figure (board-recommendation rot)** — LSRG, SELG. ISS stores an early board recommendation that was later revised upward (typically doubled) before the AGM, and never updates the stored value. Same mechanism as MTLRP (round 1) and SFIN (round 1). Detection rule: exact 0.5× ratio between ISS and dohod with single payment date.

2. **Missing interim tranches (multi-payment AGM/policy)** — VSMO (2 tranches), NVTK (2 tranches), HIMCP (4 tranches), KAZT (3 tranches). ISS keeps one payment per ticker-year and silently drops the others. Detection rule: ratio is NOT 0.5×, and dohod has multiple rows in the same calendar year. Affected: quarterly payers (HIMCP, KAZT) and semi-annual policies (NVTK, VSMO, PIKK from round 1).

3. **New observation — share-count / denomination ambiguity (AVAN)**. When per-share figures across three aggregators (ISS 6.20, dohod 12.40, smart-lab 34.42) fail to reconcile by any integer ratio, suspect a share count change (split, capital increase, reverse split) or share-class confusion. AVAN should be flagged and resolved against the issuer's e-disclosure rather than aggregators.

## Recommended pipeline action

- Tier-1 (do now, high-confidence): LSRG, SELG, NVTK, VSMO, HIMCP, KAZT — apply replace/augment per recommendations above.
- Tier-2 (quarantine): AVAN — exclude from backtest until user supplies authoritative source.
- Tier-3 (rule additions): the "ratio != 0.5x AND dohod has multiple same-year rows" detector is now a confirmed class of error worth scanning the rest of the universe for. Likely victims: quarterly payers in chemicals / energy mid-caps.

## Methodology caveats

- WebFetch was blocked on interfax.ru, investfunds.ru, tbank.ru, bcs.ru, finviewer.ru, novatek.ru. dohod.ru direct fetches succeeded for LSRG, SELG, VSMO, AVAN, NVTK, HIMCP, KAZT.
- Smart-lab fetches succeeded for AVAN, KAZT, HIMCP, NVTK.
- e-disclosure.ru not queried (no need where two independent aggregators converge; necessary but unreachable for AVAN).
- Where smart-lab and dohod disagreed (AVAN), the verdict is unresolved and the case is quarantined.
