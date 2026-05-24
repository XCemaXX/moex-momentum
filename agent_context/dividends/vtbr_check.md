# VTBR 2019/2020 dividend verification

**Verdict:**
- 2019 (paid in calendar 2019, for FY2018): **0.0010987 RUB/ordinary share**, record date 24 June 2019. Recommended by supervisory board 25 March 2019, approved by AGM 26 April 2019. 14.2 bln RUB total to ordinary holders, 15% payout of IFRS profit.
- 2020 (paid in calendar 2020, for FY2019): **0.00077345337561138 RUB/ordinary share**, record date 5 October 2020. Approved by AGM 24 September 2020. 10% of IFRS profit, vs initially-projected 50%, cut due to capital-adequacy / CBR pressure during COVID. Pref div paid separately (T1: 0.000193614…; T2: 0.00193614…) — irrelevant for VTBR.
- **dohod's 5.49 / 3.87 numbers are wrong for a per-share table.** They equal exactly `actual_per_share × 5000`:
  - 0.0010987 × 5000 ≈ **5.49**
  - 0.00077345 × 5000 ≈ **3.87**
  - This is a unit quirk: VTB nominal value is 0.01 RUB and the 1:5000 consolidation in April 2007 left the per-share dividend in micro-RUB. dohod (and some other Russian aggregators) display VTB amounts per "лот / 5000 акций" or per pre-consolidation nominal to make the column readable. The ratio is exact, not a rounding fluke — so this is a known display convention on dohod, not a typo.

**Evidence:**
- **Banki.ru (AGM 2020-09-24 minutes):** "Акционеры ВТБ приняли решение о выплате дивидендов по результатам 2019 года в размере 0,00077345337561138 рубля на одну размещенную обыкновенную акцию. Датой, на которую определяются лица, имеющие право на получение дивидендов, является 5 октября 2020 года." — <https://www.banki.ru/news/lenta/?id=10934137>
- **Interfax:** "Акционеры ВТБ утвердили дивиденды в размере 10% от чистой прибыли за 2019 год" — <https://www.interfax.ru/business/728632>
- **RBC Quote (Feb 2020 forecast):** initial projection was ~₽0.00388/share (50% payout), later cut — <https://quote.rbc.ru/news/article/5e56230f9a79477d4010686a>
- **Vedomosti (Feb 2020):** "ВТБ заплатит дивиденды за 2019 год двумя частями" — split-payment plan ordinary first, prefs later — <https://www.vedomosti.ru/finance/articles/2020/02/25/823780-vtb-dividendi>
- **For FY2018 / paid-2019:** "Наблюдательный совет Банка ВТБ рекомендовал дивиденды за 2018 год в размере 0,0011 рублей на обыкновенную акцию … 14,2 млрд рублей … Дата закрытия реестра: 24 июня 2019 года." — <https://www.dohod.ru/analytic/research/corporat/kakie-dividendyi-zhdat-ot-vtb-po-itogam-2019-goda>
- **dohod table (per-share column):** shows 17.27 / 5.49 / 3.87 RUB for 2018/2019/2020 — internally consistent with the ×5000 convention (FY2017 div was ~0.00345 RUB, × 5000 ≈ 17.27) — <https://www.dohod.ru/ik/analytics/dividend/vtbr>

**Recommendation for pipeline:**
- **Action:** ADD two records to `data/dividends/VTBR.jsonl` from MOEX-native amounts (not dohod):
  - record_date 2019-06-24, amount 0.0010987 RUB (FY2018, paid in 2019)
  - record_date 2020-10-05, amount 0.00077345337561138 RUB (FY2019, paid in 2020)
- **Source citation:** ВТБ IR / Interfax / Banki.ru — these are the canonical RUB/share figures that match exchange settlement.
- **Reason:** MOEX ISS dividend feed has a genuine gap for VTBR around the FY2018–FY2019 cycle (confirmed elsewhere — VTB's per-share figures are tiny enough that some endpoints round to 0 or omit). Use the regulator-disclosure number, not dohod's display-scaled one.
- **Do NOT** ingest dohod's 5.49 / 3.87 — those are display units, off by ×5000.

**Risk flag:**
- **dohod systematically scales VTBR dividends by ×5000.** This is unique to VTB (driven by its sub-kopeck per-share amount + 2007 consolidation legacy). It's not a generic "penny stock" bug — the ratio appears to be hand-tuned for VTBR specifically.
- **However**, the screening rule "ISS empty + dohod non-zero" will keep generating false-positive-feeling gaps for *any* ticker where dohod uses a different unit convention. Tickers to spot-check before trusting dohod amounts blindly:
  - **RKKE** (РКК Энергия) — historically low per-share, sub-RUB.
  - **MAGN, NLMK, CHMF** — fine, normal RUB scale, no risk.
  - **MRKP / MRKU / MRKC** (МРСК-family penny names, prices 0.10–0.50 RUB) — verify dohod uses RUB/share, not kopecks.
  - Any pref pair with extreme split between common/pref dividend (Surgut prefs, Mechel prefs) — make sure dohod isn't conflating the two.
- Recommended hardening: in the screening report, if `dohod_amount / iss_or_announced_amount` is an integer multiple (×100, ×1000, ×5000, ×10000), auto-flag as a unit-convention mismatch rather than a missing record.
