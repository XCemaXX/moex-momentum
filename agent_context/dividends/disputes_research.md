# Dividend disputes — ground-truth research

Authoritative cross-check for three disputed payments where MOEX ISS disagrees with
dohod.ru and the legacy CSV. Sources: Russian financial press (Interfax, RBC,
Forbes, Vedomosti), aggregator dividend histories (dohod, smart-lab, investmint),
issuer IR. WebFetch was blocked on several domains (mechel.ru, rbc.ru, interfax.ru,
pik-group.ru), so primary evidence is taken from WebSearch result extracts.

---

## MTLRP 2017-07-11

**Verdict: dohod correct (10.28 RUB). MOEX ISS value 5.14 is wrong (exactly half).**

**Evidence:**
- https://www.dohod.ru/ik/analytics/dividend/mtlrp — table row "11.07.2017 ... 10,28₽" for fiscal year 2016.
- https://smart-lab.ru/q/MTLR/dividend/ — "MTLRP | 07.07.2017 | 11.07.2017 | 2016 год | 10,28 ₽", yield 8.4% at price 122.1.
- https://investmint.ru/mtlrp/ — "Выплаты за 2017 и 2016 годы составляли 16,66 и 10,28 рубля на акцию" (10.28 is the per-share figure for fiscal 2016, paid in 2017).
- https://www.rbc.ru/quote/news/article/5ae098132ae5961b67a1b468 (via search extract) — "Mechel declared dividends of RUB 856 million (RUB 10.28 per preferred share) to the holders of preferred shares for 2016".
- Board recommendation at AGM 30 June 2017: $25.193 mln total to preferred-share dividends, 20% of 2016 net profit — consistent with 10.28/share given ~83.3M preferred shares outstanding.
- No source mentions a 5.14 RUB payment. The 5.14 = 10.28 / 2 ratio strongly suggests an ISS data-entry / unit error, not a real second payment.

**Confidence:** high

**Recommendation for the pipeline:**
- Action: replace ISS value with dohod (10.28 RUB). Single payment, not two.
- Reason: four independent sources (dohod, smart-lab, investmint, RBC quoting Mechel's own announcement) converge on 10.28; ISS appears to be an outlier with a value that's a clean factor-of-2 fraction — a classic data-entry artefact. No evidence of a separate 5.14 payment around that date.

---

## PIKK 2021-05-17

**Verdict: both records are real (different payments). dohod correct, legacy CSV correct on total. MOEX ISS is missing one of the two payments.**

**Evidence:**
- https://www.dohod.ru/ik/analytics/dividend/pikk — two rows for registry 2021-05-17: 22.51 (for 4кв 2020) and 22.92 (for 1кв 2021).
- https://smart-lab.ru/q/PIKK/dividend/ — confirms two distinct entries with the same registry cutoff, different periods.
- https://quote.rbc.ru/news/article/606acf1d9a794749fdff5ac2 (search extract) — PIK board recommended final 2020 dividend 22.51/share AND interim 1Q2021 dividend 22.92/share at the same AGM under the new dividend policy (semi-annual).
- Search summary of dohod/smart-lab: "total amount of dividends proposed for payment for 2020 and three months of 2021 was approximately 30 bln roubles, or 45.43 rouble per share" — 22.51 + 22.92 = 45.43. Math checks.
- Registry close 2021-05-17, last day to buy 2021-05-13 (same T+2 for both payments because both were approved at the same AGM).

**Confidence:** high

**Recommendation for the pipeline:**
- Action: accept BOTH records (22.51 + 22.92 = 45.43). Augment ISS with the missing 22.92 row.
- Reason: PIK genuinely declared two dividends at one AGM (final 2020 + interim 1Q2021) sharing the same record date. This is a known pattern under PIK's then-new semi-annual dividend policy. ISS is undercounting; legacy CSV (45.43 total) reflects reality.

---

## SFIN 2024-11-30

**Verdict: ISS wrong (stale superseded recommendation). dohod correct. Only ONE payment was made — 227.6 RUB with registry close 2024-12-23.**

**Evidence:**
- Initial Board recommendation (October 2024): 113.80 RUB/share for 9M 2024, EGM scheduled 2024-11-19, registry-close 2024-11-30. Source: Interfax https://www.interfax.ru/business/987346.
- On 2024-11-06 the Board DOUBLED the recommendation to 227.60 RUB/share BEFORE the EGM took place. Source: Interfax https://www.interfax.ru/business/990467 ("Совет директоров SFI увеличил в 2 раза рекомендуемые дивиденды за 9 месяцев"). Also smart-lab company blog https://smart-lab.ru/company/sfi/blog/1079641.php.
- Shareholders on 2024-12-12 approved the revised 227.60 RUB/share. Registry close was rescheduled to 2024-12-23. Sources: Interfax https://www.interfax.ru/business/997170, SFI IR https://sfiholding.ru/press/news/sobranie-aktsionerov-pao-esefay-utverdilo-vyplatu-dividendov-po-itogam-9-mesyatsev-2024-goda/, Forbes https://www.forbes.ru/investicii/526962, dohod https://www.dohod.ru/ik/analytics/dividend/sfin.
- Total payout 10.9 bln RUB matches 227.6/share, not 5.45 bln implied by 113.8/share.
- Search-extract summary: "Дата закрытия реестра акционеров для получения дивидендов — 23 декабря 2024 года" (registry close 2024-12-23).
- No source confirms an actual 113.8 RUB payment with registry 2024-11-30. That date and amount appear only in stale October coverage that pre-dates the Nov 6 board revision.

**Confidence:** high

**Recommendation for the pipeline:**
- Action: drop ISS's 113.8 / 2024-11-30 record; keep only dohod's 227.6 / 2024-12-23. Do NOT accept both — there was a single dividend event.
- Reason: 113.8 was a Board recommendation that was revised upward on 2024-11-06 BEFORE shareholder approval and BEFORE the original registry date. The EGM and registry date were moved (Nov 19 → Dec 12 EGM, Nov 30 → Dec 23 registry). ISS appears to have cached the stale October value and never replaced it. The 0.5× ratio is mechanical, not economic.

---

## Cross-cutting observations

- ISS has a systematic-looking issue with "Board recommendation → revised recommendation" lifecycle: it can persist an early figure even after shareholders approve a different amount on a different date. Same pattern caused MTLRP 5.14 (likely original board recommendation or per-half-share artefact) and SFIN 113.8.
- For PIKK, ISS is undercounting multi-tranche AGM approvals. Worth scanning the rest of the universe for AGMs that approved interim+final on the same record date (semi-annual dividend policies — common at PIK, MTSS, MGNT).
- The 0.5× ratio appearing twice (MTLRP 5.14 = 10.28/2; SFIN 113.8 = 227.6/2) is suspicious. Investigate whether ISS computes "per share" using diluted/treasury-adjusted share counts that diverge from the standard outstanding count for some issuers, OR whether ISS is reporting an interim/half figure for some board decisions. Not a one-off bug — looks like a class of errors.

---

## Methodology caveats

- WebFetch was blocked on mechel.ru, mechel.com, interfax.ru, rbc.ru, pik-group.ru, investmint.ru. Evidence is drawn from WebSearch result summaries that quote those pages. Where quotes were given verbatim ("10,28₽", "227,6 руб."), confidence is high.
- e-disclosure.ru was not directly queried (anti-bot/login wall expected); not needed because issuer IR + tier-1 press converge.
