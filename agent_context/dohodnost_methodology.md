# Methodology of the channel "Как приручить доходность" (KPD)

Extracted from the Telegram export `raw_sources/dohodnost_blog/result.json`
(channel "Как приручить доходность", ~1009 messages, 2021-09 to 2024+).
The author runs a multi-factor risk-premia + Markowitz strategy on Russian
equities, of which momentum (Q1) is one component.

Conventions below: each finding gives the message **id** + **date**, a short
Russian quote, and an English gloss. "Not found in export" means the channel
is silent on the point. Several deep-dive methodology posts are only reachable
via `t.me/kpd_investments/NNN` or `t.me/how_to_train_return/NNN` or
telegra.ph links; those target pages are NOT in the export — flagged as
"referenced but not in export".

---

## 1. Momentum lookback window & skip-month convention

**Baseline definition — 12-1 (12 months minus the last month).**

- **id 274, 2022-03-25:** "Традиционно, под импульсом понимается темп прироста
  курсовой стоимости за последние 12 месяцев, без учета последнего месяца."
  → "Conventionally momentum = price growth over the last 12 months, excluding
  the last month." (i.e. 12-1, with a 1-month skip.)

- **id 285, 2022-03-30:** lists the menu of lookbacks and flags the two he
  considers best: "12 месяцев (без учета последнего для исключения reversal
  эффекта)* / 9 месяцев / 6 месяцев* / 3 месяца. * - наиболее популярные
  варианты". → 12-1 skip is to avoid the short-term reversal effect; 12 and 6
  are the empirically strongest.

- **id 303, 2022-04-09 (VSMPO worked example — the regression anchor):**
  momentum = **geometric mean of 11 monthly returns**, Apr-2021…Feb-2022,
  computed at the penultimate trading day of March 2022, **skipping March
  (the last month)**. Result = **4,65%** ("средняя доходность ВСМПО-Ависма за
  предыдущие 12 месяцев без учета последнего … составит 4,65%"). This matches
  the project's frozen VSMO=4.6458% anchor. He also notes: "Я еще среднюю
  доходность делю на СКО. Однако … для подсчета СКО доходность за март
  учитывается" → he additionally divides by the standard deviation, and **the
  std DOES include the last (skipped) month**, unlike the mean.

**Refined / final formula — risk-adjusted blend of 12-1 and 6-1 (2024).**

- **id 895, 2024-06-17:** after a curve-fitting search to maximise cumulative
  Q1-Q4 spread, the best formula is:
  `(r(12-1)*a + r(6-1)*b) / СКО(12)`, with **a = 0.9, b = 0.1**, where
  r(12-1) = return over prior 12 months excl. last; r(6-1) = return over prior
  6 months excl. last; СКО(12) = std of the last 12 monthly returns.
  "Чем выше b, тем … ниже результат … небольшую долю для r(6-1) выделить
  все-таки стоит." A pure 6-1 momentum (a=0,b=1) is weak. He stresses momentum
  is robust to a/b: "Q1-Q4 всегда остается положительным."
  (id 896, 898 are companion charts / robustness over 100 rolling 5y windows;
  the a=0.9/b=0.1 combo scored 95/100.)

**Net:** momentum is **risk-adjusted** (divided by 12-month volatility), not a
raw price ratio. Skip-month = 1. The deployed signal is a 0.9·(12-1)+0.1·(6-1)
return blend over std(12), an evolution of the simple 12-1 geometric mean.

## 2. Rebalance frequency

**Monthly.** Computed at the penultimate trading day of each month, traded the
next day.

- **id 285, 2022-03-30:** "Импульс … я считаю в конце каждого месяца в
  предпоследний торговый день, чтобы провести ребалансировку портфеля на
  следующий. Несмотря на частую ребалансировку, комиссия терпима, так как
  портфель меняется незначительно." → momentum recomputed end of every month
  (penultimate trading day), portfolio rebalanced the following day; turnover
  is low so costs stay tolerable.
- **id 92, 2021-11-15:** "ежемесячная оптимизация с учетом издержек … Рекомендуемые
  доли не меняются значительно на коротких промежутках времени." → monthly
  optimization; weights are sticky month-to-month.

**Important distinction vs the value premium:** the **annual** "в начале июня
каждого года" cadence (id 92, 2021-11-15) applies to **ranking stocks for the
risk-premium time-series construction** (e.g. P/B sort for the value premium),
NOT to portfolio rebalancing. Portfolio rebalance = monthly. Do not conflate.

## 3. Universe & selection

- Universe = **MOEX Broad Market Index ("индекс широкого рынка Мосбиржи")**.
  - **id 274 / 285 / 305 etc.:** "Momentum Q1 - 25% акций из индекса широкого
    рынка, у которых наибольший импульс."
- For backtests he uses a **survivorship-inclusive** sample:
  **id 884, ~2024-06:** "В ней содержатся практически все акции, которые хотя
  бы раз побывали в индексе широкого рынка Мосбиржи." → "contains practically
  all stocks that were in the MOEX Broad Market Index at least once" — i.e.
  historical members are kept, mitigating survivorship bias.
- Approximate size in published monthly tables: **~88-92 tickers**, split into
  4 quartiles of ~22-23 names each (see id 351/412 lists). He notes the index
  composition needs periodic refresh: id 351 P.S. "Надо бы актуализировать
  состав индекса широкого рынка".
- **Entry filter for new IPOs:** not explicitly stated. Implicitly a stock
  needs ≥12 months of price history to compute 12-1 momentum, so fresh IPOs
  are excluded until they have the lookback. **Not stated explicitly in export.**
- Liquidity: he occasionally drops illiquid names manually (id ~205: "с их
  ликвидностью нельзя будет быстро закрыть позицию"), but there is **no formal
  liquidity screen** beyond Broad-Market membership stated in the export.

## 4. Quartiles vs quintiles; bucket boundaries

**QUARTILES — 4 buckets, equal count. He never uses quintiles.**

- The string "квинтил" appears **0 times** in the export. Any caption reading
  "квинтилей Q1-Q4" is a mislabel; the author's text is uniformly "квартили"
  with labels Q1..Q4.
- **id 884:** "делят множество акций на 4 равные по количеству тикеров группы …
  исключить 25% акций". → split into **4 groups equal by ticker count** (equal
  count, NOT cap-weighted). 25% per bucket.
- **id ~735 (analyst-critique post):** "делим выборку акций … на
  терцили/квартили/децили". → standard academic equal-count cut.
- Bucket count for Q1 holding is **flexible**: id 274 "Не обязательно покупать
  именно 25% … Можно купить 20%, 30% или 10%". Q1 = highest-momentum names,
  Q4 = lowest.
- Within-quartile weighting for the academic premium series is **equal weight**
  (he refers to "равновзвешенный индекс" in modelling posts, id ~735).

## 5. Stop-loss rule on Q1 momentum names

**Fully specified in-channel (id 135, 2021-12-07).** Trigger relative to the
**previous month's closing price**, applied to high-momentum (Q1) stocks:

- Quote: "акцию можно продавать, если цена … опустилась ниже цены закрытия
  предыдущего месяца на 5-10%." Then his own calibrated thresholds:
  1. **Drop > 5.5%** from prior-month close **if market "weakness" is
     expected**. "Weakness" = (a) the short-OFZ index **RGBICP1Y (RUGBICP1Y)
     is falling** AND (b) the **OECD CLI is not rising**.
  2. **Drop > 8.5%** from prior-month close **if no weakness expected**.
  - Fallback: "можно просто выставить оповещения в диапазоне 5-10% и смотреть
    по ситуации."
- Rationale (id 92, 2021-11-15): stop-losses on Q1 momentum names sharply
  reduce portfolio drawdown; cites *When do stop-loss rules stop losses?* and
  *Taming Momentum Crashes: A Simple Stop-Loss Strategy* (Han et al.).
- Live examples of him acting on it: id 100 (sold all RASP), id 104 ("вышел по
  стоп-лоссу" from RUAL, AMEZ, TTLK, RASP), id ~125 (sold TCSG, AQUA, HHRU).
- Mechanics nuance: it is a **monthly-anchored** stop (reference resets to each
  month's close), regime-conditional on bond/macro signals — not a fixed
  trailing stop.

## 6. Tax / commission / bid-ask treatment

- **Commissions + spread are modelled; taxes are NOT mentioned.**
- **id 92, 2021-11-15:** backtest "с учетом издержек (комиссия брокера и биржи,
  bid-ask spread)". → broker commission + exchange commission + bid-ask spread.
- **id 412, 2022-08-30:** "Теперь динамика квартилей будет учитывать
  трансакционные издержки: комиссию брокера, комиссию биржи и спред." → the
  *published quartile charts* only started including transaction costs from
  Aug-2022; earlier charts were gross of costs.
- **Taxes:** **not found in export.** No mention of dividend/capital-gains tax
  in the backtest.

## 7. Markowitz optimization step (how quartile weights are chosen)

**id 92 (2021-11-15), id 199 (2022-01-26), id 274 (2022-03-25), id ~260** —
the full pipeline:

1. Build monthly return series for each quartile of each premium (Market, Size,
   Value, Profitability, Investment, Momentum).
2. **Time-series regression** per quartile: quartile return ~ risk-premia →
   sensitivity (loading) coefficients.
3. **Cross-sectional regression**: mean excess return of quartile ~ loadings →
   estimated risk-premium magnitudes & significance.
4. **Expected return of each quartile** = Σ (premium × sensitivity).
5. **Markowitz**: "максимизирую доходность с ограничением на волатильность.
   Уровень волатильности … равен волатильности индекса МосБиржи." → maximise
   expected return s.t. **portfolio vol = MOEX index vol** (target vol is a
   risk-profile choice). Output = recommended **weight per quartile**.
6. Stock weight = sum of its weights across the quartiles it belongs to
   (id 199 worked GAZP example: 70.9% − 6.33% + 17.17% − 2.61% + 4.98%).

Key results:
- **With NO short constraint** (id 199): model longs Momentum Q1, Value Q4,
  Profitability Q1; shorts Value Q1/Q2, Momentum Q3/Q4, Profitability Q3/Q4.
- **WITH short constraint** (long-only, id 274 / id ~210): collapses to
  essentially "always buy momentum (Q1)" — "если запретить короткие продажи …
  всегда покупай моментум" (id ~210). So for a long-only investor the strategy
  ≈ long Momentum Q1.
- He optimizes at the **quartile** level, not individual stocks, because
  quartile factor loadings are far more stable than single-stock loadings
  (id 96/97: GAZP migrated Momentum Q3→Q2 over 2011-2021). Argues
  quartile-level covariances are more stable than asset/sector/stock-level.
- Indivisibility caveat (id 92): "акции - не бесконечно делимый актив … акции с
  малыми долями я могу и совсем проигнорировать" — small recommended weights
  may be dropped in live trading.
- Note: **Value Q4 (high P/B) is the favored value bucket**, the opposite of
  the textbook value premium (low P/B). This is an empirical finding for the RU
  market in his regressions, not a sign convention error.

## 8. Dividends, splits, delistings, survivorship

- **Dividends:**
  - In the **momentum signal** they ARE incorporated: id 303 "В один из месяцев
    были выплачены дивиденды … корректируем доходность за месяц на размер
    дивидендов." → monthly returns are total-return (div-adjusted).
  - In the **published quartile-performance charts** they are **excluded**:
    id 351 "график доходностей нарастающим итогом (без дивидендов)"; id 412
    "Дивиденды все еще не учитываются" + he added MCFTRR (MOEX total-return
    index) only as a visual benchmark. So chart equity curves understate
    div-paying names.
- **Survivorship:** addressed — backtest sample = all stocks ever in the Broad
  Market Index (id 884), so delisted/dropped names are retained historically.
- **Splits:** **not found in export** (no explicit split-adjustment statement;
  presumably handled via the price feed).
- **Delistings:** discussed only for ETFs/FinEx (id ~470), not as a systematic
  rule for the equity backtest. **Not found in export** for the strategy.

---

## Referenced-but-not-in-export deep dives (closed channel / telegra.ph)

These hold the fuller methodology but their content is NOT in this export — do
not fabricate:
- `t.me/kpd_investments/303` — VSMPO impulse worked example (its text WAS
  re-posted as id 303 here, so it IS available).
- `t.me/kpd_investments/135` / `t.me/how_to_train_return/92` — stop-loss
  research (key numbers are in id 135 above; underlying study is external).
- `t.me/kpd_investments/188`, `/187`, `/191`, `/220` (and the
  `how_to_train_return` mirrors) — risk-premium estimates, sensitivity tables,
  and the optimal-portfolio result. Tables themselves NOT in export.
- Various `telegra.ph` images — chart screenshots, not in export.
