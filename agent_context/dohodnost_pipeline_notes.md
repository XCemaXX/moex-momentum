# Dohodnost blog — pipeline-relevant findings

Mined from `raw_sources/dohodnost_blog/result.json` (channel "Как приручить доходность", ~1009 msgs, 2021-09 to 2024+). Only items that bear on building/validating a Russian-equity momentum pipeline are recorded. Each entry: msg id, date, short RU quote, EN gloss.

NOTE: many deep-dive posts live behind `t.me/kpd_investments/*` and `telegra.ph/*` links whose bodies are NOT in this export (kpd_investments is closed). Those are marked "behind link, not in export".

---

## 1. Corporate-action handling (splits, delistings, renames, redomicile)

- **msg 858, 2024-05-27** — *the most important data-quality post.* He published his "База данных.xlsx" and listed splits / "erasing extra zeros" (стирания лишних нулей) that are **NOT corrected** in his raw prices and dividends — the user must adjust them himself:
  > "Сплиты и 'стирания лишних нулей' в ценах и дивидендах не скорректированы, поэтому, если будете работать с данными и считать доходности, корректируйте. Таких случаев немного: **Фосагро в марте 2012, ИнтерРАО в январе 2015, Транснефть в феврале 2024 и НорНикель в апреле 2024.**"
  EN: splits/denomination-changes are left RAW in his sheet. Four cases to hand-adjust: **PHOR 2012-03, IRAO 2015-01, TRNFP 2024-02, GMKN 2024-04.** Directly cross-checkable against our split adjustments.
  - Link for "стирания лишних нулей": kommersant.ru/doc/2437272 (Inter RAO 2015 nominal redenomination). Use as an external anchor.

- **msg 598, 2023-05-30** — delisting policy + no historical revision:
  > "Ашинский метзавод собирается на делистинг, поэтому больше он для расчета Q1-Q4 использоваться не будет. Прошлая динамика Q1-Q4, естественно, не пересматривается."
  EN: **AMEZ** going to delisting → dropped from FUTURE quartile calc; **past quartile dynamics are NOT restated.** Same post adds EELT and ISKJ to the DB and again states past Q1-Q4 do not change. Universe-maintenance rule = forward-only edits, no look-ahead rewrite.

- **msg 379, 2022-07-13** — **POGR (Petropavlovsk)** bankruptcy flagged; it sits in Q4 (low momentum). Warns against buying Q4 names. Relevant for a delisting/bankruptcy hazard list.

- **msg 488, 2023-02-25** — universe gap quirk: **SIBN (Gazprom Neft) is absent from MOEXBMI**, so it was missing from his DB; he added it manually (in the DB, not the portfolio), dropping OBUV/Obuv Rossii (ORUP).
  > "Заметил, что в моей базе не хватает газпромнефти... его нет в базе расчета индекса широкого рынка... ORUP ушел, SIBN пришел."
  EN: even the "broad-market" index omits some liquid names; manual universe patching needed. Universe source link: moex.com/ru/index/MOEXBMI/constituents/.

- **Redomicile (X5/HEAD/YDEX/TCS→T):** essentially NOT discussed as a data-handling issue in the export. FIVE appears as ticker `FIVE` in his quartile lists through 2023 (msg 598). No statement on how he bridges DR→share conversions for momentum. The one redomicile mention (msg ~) is a political-philosophy quote, not methodology. Detail behind links, not in export.

- **msg 9762, ~2022** — note on residents buying DRs OTC, converting to shares, selling on MOEX (arbitrage channel). Context only, not momentum-construction.

## 2. Dividend treatment

- **msg 412, 2022-08-30** — first cost upgrade: quartile dynamics began including transaction costs, but
  > "Дивиденды все еще не учитываются."
  EN: at this stage dividends were STILL excluded from the published Q1-Q4 dynamics.

- **msg 452, 2022-11-04** — *dividend policy switch:*
  > "Теперь при расчете величины импульса и ранжирования акций по квартилям я буду учитывать не только изменение цены, но и полученные дивиденды... Дивиденды, конечно, **за вычетом налогов**, чтобы корректно сравнивать динамику Q1-Q4 с **MCFTRR**."
  EN: from Nov 2022 momentum value AND ranking include dividends, **net of tax**, to be comparable to MCFTRR (the *net* total-return index, double-R suffix). Before this date momentum was price-only.

- **msg 858, 2024-05-27** — in the DB, dividends are stored **gross, per share, placed in the month the dividend record-cut (отсечка) fell**:
  > "На втором листе дивиденды на 1 акцию. Расставлены по тем месяцам, на которые пришлась дивидендная отсечка."
  EN: dividend timing keyed to ex-/record-cut month, not payment date. Stored gross (he tells the reader to apply tax himself when computing returns).

- Benchmark choice is load-bearing: he compares to **MCFTRR** = net-of-tax total return. If we want apples-to-apples with his published numbers, our dividends must be net-of-Russian-corporate-tax. Gross TR (MCFTR) would overstate vs his series.

## 3. Tickers flagged problematic / illiquid / "шлак" (trash)

- **msg 445, 2022-10-29** — the "шлак" problem and his fix:
  > "В последнее время в Q1 стало попадать слишком много шлака с очень низким объемом торгов... буду отдельно публиковать состав Q1 только для акций, которые входят в индекс Мосбиржи. MomentumQ1 (индекс МосБиржи): PHOR, FIVE, MGNT, HYDR, GAZP, TATNP, TATN, OZON, MTSS, PIKK."
  EN: broad-market universe (MOEXBMI) injects illiquid junk into Q1 — low-volume names that "stand still while liquid names fall, then stay still when liquid names rally." His mitigation: publish a **second Q1 restricted to IMOEX (blue-chip) constituents**. Implication for us: a liquidity screen materially changes Q1 membership.

- **msg 10739, ~2022** — "Столько шлака в Q1, даже не знаю, какой выбрать :)" (same complaint, lighter).

- Specific names he treats as marginal / DB-only (not portfolio): EELT (Европейская электротехника — "просто понравился"), ISKJ (Институт стволовых клеток), OBUV/ORUP (Обувь России), POGR (bankrupt). Recurrent low-liquidity tickers appearing in his Q1: AMEZ, KAZT, TGKB, DVEC, MRKU, NKHP, CHMK, TTLK, OGKB.

## 4. Survivorship / forward-looking bias

- **msg 858, 2024-05-27** — explicit anti-survivorship design:
  > "Под 'собрать данные по всем акциям' я имею виду вообще по всем, в том числе по тем, которые провели делистинг. **Автовазы, Верофармы, Дорогобужи, энергосбыты** не первой свежести — никто не должен уйти не посчитанным. Так мы если не устраняем полностью, то сильно уменьшаем **forward-looking bias**."
  EN: DB intentionally includes delisted names (AvtoVAZ, Veropharm, Dorogobuzh, defunct energy-sbyts) to reduce look-ahead/survivorship bias. Universe = anything that was EVER in MOEXBMI 2012-2024 with ≥12m history, plus a few extras (EELT).

- Combined with msg 598's "past dynamics not revised" rule: he builds the universe point-in-time forward and never rewrites history. That is the correct survivorship discipline — worth replicating and validating our pipeline does the same.

## 5. Momentum-crash / 2022 MOEX halt (market closed ~Feb 25 – Mar 24 2022)

- **msg 285, 2022-03-30** — momentum DEFINITION post (timing matters for the gap): impulse = mean monthly growth over trailing 12m **excluding the last month** (reversal), divided by SD; but **for the SD, do NOT exclude the last month**; computed on the **second-to-last trading day of the month**, rebalance next month.
  > "...средний темп прироста за последние 12 месяцев (исключая последний месяц), деленный на СКО... при подсчете СКО последний месяц лучше не исключать. Импульс... считаю в конце каждого месяца в предпоследний торговый день."
  EN: this is the exact formula and rebalance timing. Note he uses a **risk-adjusted** momentum (return/vol), not raw 12-1.

- **msg ~ (line 8286), 2022-03-25** — at partial reopening only IMOEX constituents traded; his target stocks weren't trading:
  > "...многие из интересующих меня акций не торгуются, так как не входят в индекс МосБиржи."
  EN: during/after the halt the tradable universe collapsed to blue chips; momentum signal for non-IMOEX names had a data gap.

- **msg 7106, 2022-02 results** — crash mitigation in practice: portfolio **+0.9% vs index −30%** because he held index-futures shorts + large ruble cash going in. Survivors held through the halt: VSMO, AKRN, US-equity fund, near OFZ, index-future shorts.
  - No explicit statement on how he stitched the missing Feb-Mar months into the 12-month momentum window (whether he treated it as a single gap or carried the last pre-halt price). Not resolved in export — likely behind links.

## 6. Stop-losses, position sizing, transaction costs (MOEX-specific)

- **msg 92, 2021-11-15** — full strategy + costs + stop-losses:
  > "...ежемесячная оптимизация **с учетом издержек (комиссия брокера и биржи, bid-ask spread)**... Рекомендуемые доли не меняются значительно... что позволяет держать транзакционные издержки на низком уровне... есть небольшая хитрость... для акций [первого квартиля] целесообразно применение **стоп-лоссов**... очень сильно снижают уровень просадки портфеля."
  EN: position sizing via Markowitz max-return s.t. vol ≤ IMOEX vol; costs modelled = broker + exchange commission + bid-ask spread. **Stop-losses applied specifically to Q1 (high-momentum) names** to cut drawdown — his stated momentum-crash control. Tiny-weight names are dropped (shares not infinitely divisible).

- **msg 452, 2022-11-04** — cost set expanded to **broker commission + exchange commission + bid-ask spread + slippage (проскальзывание)**. So by late 2022 his published Q1-Q4 net curve nets these four cost components.

- **msg 412, 2022-08-30** — first introduction of costs into the published quartile dynamics (broker + exchange commission + spread).

- **msg 1084 / 1180** (OFZ-futures sub-strategy) — early evidence he models bid-ask spread carefully on illiquid instruments; relevant as a mindset, not equities.

- Rebalance cadence: monthly, on the second-to-last trading day; he stresses turnover is low so commissions are tolerable (msg 285, 92).

## 7. His data infrastructure ("База данных")

- **msg 858, 2024-05-27** — the DB: monthly prices + dividends for every stock that was ever in MOEXBMI 2012-2024 (plus extras), ≥12m history, incl. delisted. Sheet 1 = price per share, usually last trading day of month (sometimes 2nd-to-last day / late session — "разница не критичная"). Sheet 2 = dividends per share by ex-/record-cut month. Splits NOT adjusted (see Theme 1). File: `База данных.xlsx` (not included in export).

- **msg 474, 2023-01-30** — DB grew to **109 stocks**; added CIAN, FIXP, GEMC (Евромедцентр), POSI, RENI, SFTL, SMLT, SGZH, SPBE, VKCO.
  > "Обновил свою базу данных для расчета моментума... Итого моя база данных теперь насчитывает 109 акций."

- **msg 488, 2023-02-25** — universe source = **MOEXBMI constituents list** (moex.com/ru/index/MOEXBMI/constituents/); manual patching when MOEXBMI omits a liquid name (SIBN).

- He uses EViews for regressions (msg 18125) — not part of the price DB, but indicates the broad-market risk-premium model is separate from the momentum ranking.

## 8. Surprising / contrarian items that could change how we build or validate

- **Risk-adjusted momentum, not vanilla 12-1.** His signal is return/vol (avg growth ÷ SD), with an asymmetric window: numerator excludes the last month, denominator (SD) includes it (msg 285, 8687). If our pipeline implements plain 12-1, our quartiles will diverge from his published lists — useful as a differential test but a mismatch source.

- **Benchmark = MCFTRR (net total return).** Validate against the net, not gross, index (Theme 2). His dividends are net-of-tax in the published curve.

- **Splits left raw in source data** with a known 4-case list (PHOR 2012-03, IRAO 2015-01, TRNFP 2024-02, GMKN 2024-04). These are concrete adjustment anchors to verify our corporate-action layer against (Theme 1).

- **Two universes by liquidity** (full MOEXBMI vs IMOEX-only Q1). The "шлак" effect means a momentum backtest on full broad-market will be dominated by illiquid names that don't trade at the signal — survivorship-clean but un-tradeable. Any tradeability claim must apply a liquidity/IMOEX filter (msg 445).

- **Forward-only universe edits, no historical restatement** (msg 598). If we ever recompute historical quartiles after adding/removing a ticker, we break comparability with his series and risk look-ahead.

- **He admits price source is fuzzy** ("usually last trading day, sometimes 2nd-to-last day, late session — not critical"). For exact reproduction this introduces small noise; our pipeline using a strict month-end close will not byte-match his sheet.
