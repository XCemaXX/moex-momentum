# Quantitative claims mined from "Как приручить доходность" Telegram export

Source file: `raw_sources/dohodnost_blog/result.json` (channel export, 1003 text messages, 2021-09-06 to 2026-04-30).
References use `msg id` from the export. Numbers are recorded **verbatim** (Russian decimal comma kept) with their post date.

**CRITICAL CAVEAT.** The author posts two different things, do not conflate them:
- **Расчетный Q1–Q4** = his backtest of the cross-sectional momentum quartiles on the MOEX broad-market universe. This is what we want to validate against. Almost every numeric Q1/Q4 *level* (the cumulative multiple) lives in attached **chart images** or in the `telegra.ph` / `t.me/kpd_investments` links that are **NOT in this export** (kpd channel is closed). Marked "behind link/image, not in export" below.
- **Мой портфель** = his *personal* live account: a blend of Q1 stocks + OFZ/corporate bonds + index-futures hedges + (earlier) a frozen FXUS ETF + stop-losses. The monthly "итоги" returns are for this mixed account, NOT for pure Q1. Useful as context only, not as a clean momentum anchor.

---

## A. Methodology / universe / data construction (the anchors that matter most)

| id | date | claim |
|----|------|-------|
| 92 | 2021-11-15 | Methodology: each June rank all stocks by factor into quartiles; Q1 = best, Q4 = worst; premium = monthly return(Q1) − return(Q4); then OLS of quartile returns on premium time series. |
| 274 | 2022-03-25 | Momentum defined as price growth over **last 12 months excluding the last month** (12-1). Q1 = top 25% by impulse from the broad-market index. |
| 303 | 2022-04-09 | "Считаем импульс на примере ВСМПО-Ависма" — the worked VSMO impulse example (this is the externally-verified anchor; full calc behind kpd link, not in export). |
| 412 | 2022-08-30 | From this date Q1–Q4 dynamics include transaction costs (broker + exchange commission + spread). Dividends NOT yet included. MCFTRR added as benchmark line. |
| 452 | 2022-11-04 | From this date impulse ranking AND published Q1–Q4 dynamics include dividends **net of tax** (to compare like-for-like with MCFTRR). Costs still included. |
| 895 | 2024-06-17 | Curve-fit best momentum formula: `(r(12-1)*0.9 + r(6-1)*0.1) / SD(12)`. Pure 6-month momentum (a=0,b=1): cumulative Q1−Q4 "едва достигает 7,5" (≈7.5x spread). |
| 898 | 2024-06-23 | Rolling 5-yr windows: **first window = Feb-2011 → Feb-2016**; last = May-2019 → May-2024 (100 windows). ⇒ **series starts February 2011.** Combo a=0.9,b=0.1 won 95/100 windows. |
| 474 | 2023-01-30 | Database = **109 stocks** after adding CIAN, FIXP, GEMC, POSI, RENI, SOFL, SMLT, SGZH, SPBE, VKCO. |
| 858 | 2024-05-27 | Database goal: every stock that was **ever in the MOEX broad-market index 2012–2024** (incl. delisted: AVAZ, Veropharm, Dorogobuzh, energosbyts) to cut forward-looking bias. Monthly close prices + dividends by ex-date. Splits NOT adjusted: FosAgro Mar-2012, InterRAO Jan-2015, Transneft Feb-2024, NorNickel Apr-2024. |
| 852 | 2024-05-13 | After fixing missed dividends: all quartile returns rose; hierarchy tightened to strict **Q1>Q2>Q3>Q4** (was Q2<Q3 before). |
| 859 | 2024-05-27 | After DB rework: Q1 stays high, Q4 low, hierarchy **Q1>Q2>Q3>Q4** holds; Q2/Q3 dropped (new names underperformed). |
| 503 | 2023-03-09 | Q1 did NOT beat MCFTRR from end-2017 to end-2019 (momentum can lag for years). |

## B. Расчетный (backtest) quartile returns stated as numbers

| id | date | claim |
|----|------|-------|
| 962 | 2025-01-04 | **Calendar 2024 quartile returns**: Q1 **−11,52%**, Q2 −14,9%, Q3 −22,3%, Q4 −21,57%. (Premium positive even in a down year.) Context: MCFTRR +0,5%, MESMTRR (mid/small cap) −12% in 2024. |
| 1029 | 2026-01-02 | **Calendar 2025 quartile returns**: Q1 **+17,08%**, Q2 −6,15%, Q3 −9,34%, Q4 −7,54%. Context: MOEX index +2,01%, OFZ index +23,09%. |
| — | monthly 2025-26 | Monthly Q1–Q4 constituent posts (967, 972, 976, 980, 984, 988, 992, 997, 1001, 1011, 1017, 1025, 1035, 1041, 1047, 1052) attach **cumulative Q1–Q4 charts + the DB file in comments** — the cumulative levels are in those attachments, not in post text. |
| — | full equity cumulative multiple | **No explicit "Q1 вырос в N раз" for the equity backtest appears in the text anywhere.** Only the chart (image) shows it. Marked behind image, not in export. |

## C. Bond/VDO momentum backtest (separate from equities; recent)

| id | date | claim |
|----|------|-------|
| 1015 | 2025-11-14 | VDO (high-yield) momentum, 6-1 momentum, RUCBHYTR universe, archive only from 2024 (short period): Q1 **+84,24%**, Q4 **−8,57%**, RUCBHYTR +31,99% (no costs). |
| 1021 | 2025-12-09 | After parser fix: Q1 **+48,7%**, Q4 +11,8%, RUCBHYTR +31,99%. With costs (0.58% one-way / 1.16% round): Q1 drops 48,7% → **33%**. |
| 1024 | 2025-12-28 | Investment-grade corp momentum (near/far switch), Apr-2019→Nov-2025: **+111,6%** (on RUCBCP3YNS signal) or **+132,2%** (on RUGBICP3Y signal). RUCBTRNS +80,6%. |

## D. Risk-premium estimates (Russian market, annualized) — id 187, 2022-01-13

OLS estimates, significance by stars:
- **Market risk premium: +14,44%/yr** (significant) — RU stocks over short OFZ.
- **Momentum premium: +14,16%/yr** (significant at 1%) — top-12m vs worst-12m.
- **Value (low P/B): −3,89%/yr** — low-P/B *loses* to high-P/B on RU market.
- **Size and Investments premia: NOT significant.**
- (id 191, 2022-01-17) Expected returns ~"15% годовых" cited for an example quartile (Gazprom Momentum Q2). Markowitz optimizer recommends Momentum Q1 + Value Q4 + Profitability Q1.
- (id 617/623, 2023-06) Japan momentum alpha: **+4,28%/yr** (his estimate, Nov-1990→Apr-2023) vs Asness 9,3%; with Asness value proxy 7,57%/yr — these are FRENCH-data / Japan, not RU. Cross-check noise, not an RU anchor.

## E. Personal mixed-portfolio monthly/yearly "итоги" (context only — NOT pure Q1)

Series first published **April 2021** (id 124). "Доходность портфеля vs MCFTRR" cumulative since Apr-2021:

| id | date (as-of) | cumulative portfolio | cumulative MCFTRR | notes |
|----|------|------|------|------|
| 173 | 2021-12 | 2021: **+33,7%** | +12,02% | drawdown 6,83% vs 15,48% |
| 291 | 2022-03 | +31,96% | −19,67% | max DD 14,03% vs 51,37% |
| 326 | 2022-04 | +33,32% | −27,35% | |
| 343 | 2022-05 | +29,41% | −29,86% | |
| 372 | 2022-06 | +28,16% | −34,32% | |
| 398 | 2022-07 | cum +25,21% | −33,4% | Sharpe 0,35 vs −0,27; vol 4,06% vs 9,12%; avg monthly +1,42% |
| 418 | 2022-08 | +29,63% | −27,8% | Sharpe 0,39; vol 3,96% |
| 434 | 2022-09 | +22,52% | −40,98% | Sharpe 0,27 |
| 447 | 2022-10 | +26,36% | −32,23% | Sharpe 0,3; vol 4,10% |
| 532 | 2023-03 | +54,36% | −21,01% | Mar-2023 month +16,3% vs 8,77%; Q1-2023 +24,46% vs 14,04% |
| 571 | 2023-04 | +59,3% | −15% | |
| 606 | 2023-05 | +60,64% | −10,72% | |
| 638 | 2023-06 | +67,35% | −6,9% | |
| 660 | 2023-07 | +84,66% | −2,9% | Jul month +10,34% vs 10,53% |
| 687 | 2023-08 | **+101,39%** | +8,08% | crosses 100% (portfolio doubled since Apr-2021) |
| 714 | 2023-09 | +94,34% | +4,95% | |
| 731 | 2023-10 | +92,54% | +7,61% | |
| 747 | 2023-11 | +89,3% | +6,43% | |
| 780 | 2024-01 | 2023 yr **+51,6%** vs MCFTRR +52,5%; cum +87,09% | +5,6% | benchmark switches to W·RGBITR+(1−W)·MCFTRR |
| 801 | 2024-01 | +95,4% | +10,11% | |
| 828 | 2024-02 | +95,62% | +11,56% | |
| 849 | 2024-04 | +101,2% | +19,01% | 4mo-2024 +7,53% vs 12,7% |
| 872 | 2024-05 | +95,98% | +11,55% | |
| 962 | 2025-01 | 2024 portfolio NEGATIVE for the year (underperformed benchmark) | — | see §B for 2024 quartiles |
| 1029 | 2026-01 | 2025 portfolio **+21,55%** vs MOEX +2,01% vs OFZ +23,09% | — | |

## F. Single-stock / passing anchors (cross-check candidates, use with care)

| id | date | claim |
|----|------|-------|
| 495 | 2023-03-02 | AMEZ (Ашинский метзавод) total holding return hit **100%** intraday; long-held Q1 name. |
| 515 | 2023-03-21 | AMEZ total holding return **235%**. (Bought ~early 2022 in Q1; not a clean fixed-window number.) |
| 98 | 2021-11-16 | VSMO +10,73% on a single day (Boeing memo). |
| 300 | 2022-04-06 | MOEX retail popularity Mar-2022: GAZP 28,6%, SBER 20,9%+5,7%, GMKN 11,9%, LKOH 9,5%, SNGSP 6,2%, ROSN 4,7%, YNDX 4,6%, ALRS 4%, NLMK 3,9%. |
| 142 | 2021-12-13 | MOEX index drawdowns (smart-lab user MadQuant): current 12,1%; median since 2009 = 22,2%; median since 1997 = 24,3%. |
| 662 | 2023-08-02 | MOEX index closed 3093,64 on 2023-08-01 (first time above 2022-02-22 level); MCFTRR reached that level in June. |
| 916 | 2024-09-11 | 2017 MCFTRR: max 3114,71 (Jan) → 2500,09 (Jun), ≈20% correction. |

## G. Non-RU / illustrative numbers (NOT validation anchors, logged for completeness)

- id 361/634 (2022-06): S&P500 grew ×4,6; junk-spread short strategy ×20,5.
- id 327 (2022-05): Medallion fund Sharpe 2,087 (1988–2018, gross), beta to market −1.
- id 336 (2022-05): USD/RUB 3-week momentum ×8 vs buy-and-hold USD ×2,14 (Jan-2001→May-2022).
- id 843 (2024-04): "SMART" stocks 19,6%/yr vs S&P500 9,4% (1994–2013) — illustrative of luck.
- id 1005 (2025-10): RU VDO index RUCBTRBBBNS vol 2,46% vs MCFTRR 6,92%; corr 0,37 (Jan-19→Sep-25).

---

## Data sources he uses

- **His own database ("База данных")** — primary source for the equity Q1–Q4 backtest. Self-built Excel of monthly close prices + dividends (by ex-date) for every stock ever in the MOEX broad-market index **2012–2024** plus a few extras (e.g. EELT, ISKJ); includes delisted names. Splits NOT adjusted (4 known cases, id 858). The DB file is attached in comments to every monthly post from 2025-01 onward (ids 967, 972, 976, …, 1052). Net-of-tax dividends. (ids 474, 598, 852, 858, 859, 967)
- **MOEX / Moscow Exchange site** — index compositions (broad-market index, MCFTR/MCFTRR, RGBITR, RUGBITR1Y/3Y/5Y/10Y, RUCBITR/RUCBTR series, RUCBHYTR, RUEYBCSTR, RUGROWTR, MESMTRR), index-rebalance archive (VDO archive only from 2024), retail-popularity stats. (ids 365, 411, 662, 1015)
- **Kenneth French data library** — for momentum/value premia on US & Japan markets (Fama-French). (ids 614, 617, 623)
- **smart-lab.ru** — drawdown stats (user MadQuant), other-trader strategy reviews, charts. (ids 20, 142, 402, 464, 489, 691)
- **InvestFunds** — PIF ranking (Аленка Капитал alpha test). (id 884)
- **capital-gain.ru / @capitalgainru** — drawdown & CAPE stats. (ids 692, 919, 938)
- Brokerage app **Открытие** for his live account P&L screenshots (ids 101, 114).
- Eviews for the regressions; raw data + model files posted "in comments" (not in this export). (ids 617, 623, 727)
- Macro/other: ОЭСР CLI, Maddison, Penn World Table, World Bank, Росстат, customs data — for non-investing posts only.

## Hard blockers (behind links not in this export)
- All `telegra.ph/Rezultaty-portfelya-*` monthly detail pages — full holdings/structure.
- All `t.me/kpd_investments/*` links (187, 188, 303, 632, 688, 693, 753, 895, 1015, 1021, 1024, …) — the kpd channel is closed; do NOT fabricate.
- Every attached chart/image showing the **cumulative Q1–Q4 levels and the cumulative momentum-premium curve** — not extractable from JSON text.
