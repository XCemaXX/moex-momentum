# Q017 — Reference-chart provenance (author's own words)

Source: `raw_sources/dohodnost_blog/result.json` — Telegram channel «Как приручить доходность» (kpd_investments), 1009 messages, channel created **2021-09-06** (id 1). All quotes are read from the `text` field only (flattened), `text_entities` ignored. Russian preserved verbatim; English gloss follows each quote. Every claim cites a message id.

---

## Headline

**The entire Q1–Q4 cumulative chart is a BACKTEST over a self-assembled database, not a contemporaneous track record. The pre-2021 portion (i.e. ~2011–2021, roughly the whole disputed early period) is therefore necessarily a RECONSTRUCTION** — the channel only started in Sept 2021 and the live monthly quartile/portfolio posts begin Jan–Mar 2022. The author *documents that this is a backtest* and documents the 2024 database rework, but **he never explains how the early (2011–~2021) chart was originally built, nor what data/universe underlay it before the 2024 rework.** The clean `Q1>Q2>Q3>Q4` ordering is explicitly a **2024 artifact**: before the May-2024 fixes the cumulative `Q2 < Q3` (mid-quartile inversion), and the momentum formula coefficients were curve-fit to maximize the cumulative Q1–Q4 spread over the full Feb-2011→May-2024 sample.

So on the task's three-way classification: it is a **documented backtest whose 2024 reconstruction is documented, but whose ORIGINAL early-period construction (data sourcing, universe membership history, survivorship handling before 2024) is undocumented in the export.**

---

## Theme 1 — Early-history construction: backfill / reconstruction after the 2024 DB rework?

The key fact is structural: the channel itself starts 2021-09-06 (id 1). Any chart that extends back to 2011 is, by definition, computed retrospectively. The author confirms it is a backtest run over his own DB and describes the DB being (re)built in 2024.

> **id 858 (2024-05-27):** «Доработал базу данных до удовлетворительного, по моему мнению, состояния. Целью ставилось собрать все котировки и дивиденды на каждый месяц по акциям, которые хотя бы раз входили в индекс широкого рынка с 2012 по 2024. И пару интересных тикеров типа EELT в придачу. И по которым, естественно, есть достаточная история для подсчета импульса за 12 месяцев.»
> — *Gloss:* "Reworked the database to a satisfactory state. The goal was to collect all monthly quotes and dividends for stocks that were **at least once** in the broad-market index **from 2012 to 2024**, plus a few interesting tickers like EELT, and for which there is enough history to compute 12-month momentum." Note: he says **2012**, not 2011, as the universe-membership window.

> **id 859 (2024-05-27):** «И сразу посмотрим на доходности Q1-Q4, оцененные по доработанной базе данных. Хорошая новость - высокая доходность Q1 сохранилась. Также наблюдаем низкую доходность Q4 и сохранившуюся иерархию Q1>Q2>Q3>Q4. Доходность Q2 и Q3 стала ниже, так как в основном в эти квартили попали новые акции, показавшие себя не очень хорошо.»
> — *Gloss:* "Now look at Q1–Q4 returns evaluated on the reworked DB. Good news — Q1's high return survived. We also see low Q4 and the preserved hierarchy Q1>Q2>Q3>Q4. Q2 and Q3 returns fell, because mostly newly-added stocks (that performed poorly) landed in those quartiles." → The reworked DB **re-evaluates the whole Q1–Q4 history**; adding previously-missing names changed mid-quartile returns.

> **id 852 (2024-05-13):** «Исправил ошибки в своей базе данных. Упустил дивиденды по некоторым компаниям за ряд месяцев. В результате исправлений: 1) Выросли доходности всех квартилей. 2) Иерархия стала более строгой. Если раньше **накопленная доходность Q2 была меньше Q3**, то теперь наблюдаем красивое Q1>Q2>Q3>Q4. Продолжаю обновлять и искать ошибки в своей базе. Как буду доволен ее состоянием, планирую выложить в канал.»
> — *Gloss:* "Fixed errors in my DB — I had missed dividends for some companies in some months. After the fixes: (1) all quartile returns rose; (2) the hierarchy became stricter. **Whereas before the cumulative Q2 was below Q3, now we see a nice Q1>Q2>Q3>Q4.** Still updating and hunting for errors; when satisfied I plan to publish the DB to the channel." → **Direct confirmation that the clean ordering is a post-2024-fix outcome**; pre-fix the cumulative mid-quartiles were inverted (Q2<Q3). This is the single most load-bearing statement on provenance.

> **id 858 (cont.):** «Под "собрать данные по всем акциям" я имею виду вообще по всем, в том числе по тем, которые провели делистинг. Автовазы, Верофармы, Дорогобужи, энергосбыты не первой свежести - никто не должен уйти не посчитанным. Так мы если не устраняем полностью, то сильно уменьшаем forward-looking bias.»
> — *Gloss:* "By 'collect data for all stocks' I mean literally all, including delisted ones — AvtoVAZ, Veropharm, Dorogobuzh, stale energy-sbyts — nobody should go uncounted. This way we, if not eliminate, then strongly reduce forward-looking bias." → Survivorship handling was a **2024** addition (see Theme 4).

Search results (flattened `text`): пересч* appears only at ids 889, 920 (inflation/withdrawal-rate contexts, **irrelevant**). Tokens реконструкц, задним числом, выживаемост, survivorship: **zero hits**. "переделк/переработ/перестро" → only id 594 (an oil-interview note, irrelevant). "бэктест/backtest" → only id 334 (cites Tomtosov's HSE backtest, third-party, irrelevant). So the author **never uses the words "reconstruction / backfill / survivorship / recompute"** about his own early chart. The provenance of the *original* early series (what it looked like before May 2024, where the 2011–2021 data came from) is **not described anywhere in the export.**

---

## Theme 2 — Universe / selection for the early period

The universe is the **MOEX broad-market index** (индекс широкого рынка), point-in-time membership ("at least once a member"), sliced into quartiles of ~25% by momentum. This is stated repeatedly.

> **id 274 (2022-03-25):** «Модель рекомендует покупать Momentum Q1 - 25% акций из индекса широкого рынка, у которых наибольший импульс… Не обязательно покупать именно 25% из всей выборки. Можно купить 20%, 30% или 10%...»
> — *Gloss:* "The model recommends Momentum Q1 — the 25% of broad-market-index stocks with the highest momentum… You don't have to take exactly 25%; could be 20/30/10%." → Universe = broad-market index; quartile = top 25%.

> **id 858:** see Theme 1 — universe defined as "stocks that were at least once in the broad-market index from 2012 to 2024."

**Liquidity / "trash" (шлак) problem and the SECOND, blue-chip Q1 (id 445):**

> **id 445 (2022-10-29):** «В последнее время в Q1 стало попадать слишком много **шлака** с очень низким объемом торгов (ожидаемо, ведь для расчета импульса используются данные по индексу широкого рынка, там такого добра много). И мне это не нравится… Чтобы не упускать из виду ликвидные российские акции, буду отдельно публиковать состав Q1 только для акций, которые входят в **индекс Мосбиржи**. MomentumQ1 (индекс МосБиржи): PHOR, FIVE, MGNT, HYDR, GAZP, TATNP, TATN, OZON, MTSS, PIKK.»
> — *Gloss:* "Lately too much **trash** (very low trading volume) lands in Q1 — expected, since momentum is computed on the broad-market index, which has plenty of such names. I don't like it… To keep liquid Russian stocks in view, I'll **separately** publish a Q1 restricted to **IMOEX (MOEX index) members**." → Confirms the task's premise: a **second, blue-chip-only Q1** was introduced (2022-10), but as an *additional view*, **not** as the basis of the cumulative chart. The headline chart's universe remained the full broad market (trash included).

> **id 341 (2022-05-31):** «…Столько **шлака** в Q1, даже не знаю, какой выбрать :)»
> — *Gloss:* "…So much trash in Q1, I don't even know which to pick." → Same liquidity complaint, earlier.

> **id 962 (2025-01-04):** «…в базу расчета и, следовательно, в портфель могут попасть акции, которые хотя бы раз входили в широкий рынок. Большое количество акций средней и малой капитализации в базе расчета и портфеле сыграло злую шутку… Повод ли это ограничить базу расчета крупными компаниями? Не думаю. **Перед созданием канала я проводил такие тесты на трех выборках: 1) широкий рынок; 2) только крупные компании (из индекса MCFTRR); 3) только средние и малые компании (широкий рынок кроме MCFTRR). Моментум на широком рынке давал наилучший результат.**»
> — *Gloss:* "…the calc base (and hence the portfolio) can include stocks that were at least once in the broad market. The large count of mid/small-cap in the base and portfolio played a cruel joke… Is this a reason to restrict the base to large caps? I don't think so. **Before creating the channel I ran such tests on three samples: (1) broad market; (2) large caps only (MCFTRR index); (3) mid/small caps only. Momentum on the broad market gave the best result.**" → **Load-bearing.** Confirms (a) the universe choice was made by **pre-channel backtesting** (i.e. before Sept 2021, retrospective over the historical period), and (b) the broad-market universe was *selected because it backtested best* — a universe-selection decision baked into the early chart, undocumented as to data sourcing.

No liquidity filter is applied to the headline broad-market chart in the early period (the trash is explicitly *left in*); the liquidity filter / IMOEX restriction is only a parallel display (id 445) or appears later in the bond work (ids 1023, 1031).

---

## Theme 3 — Did Q2 ever beat Q1? Quartile-spread shape in early years

No statement that **Q2 beat Q1**. The only documented ordering anomaly is **Q2 below Q3** (a mid-quartile inversion), present in the cumulative chart **before** the May-2024 fix:

> **id 852:** «Если раньше накопленная доходность **Q2 была меньше Q3**, то теперь наблюдаем красивое Q1>Q2>Q3>Q4.»
> — *Gloss:* "Whereas before the cumulative Q2 was below Q3, now we see a nice Q1>Q2>Q3>Q4." → The pre-2024 chart did **not** show clean ordering in the middle. Q1's lead over Q4 is the only relationship the author treats as robust.

> **id 962 (2024 review):** «Не смотря на очень низкую доходность Q1 (-11,52%), доходность Q2-Q4 оказалась еще ниже (-14,9%, -22,3% и -21,57% соответственно). То есть, удалось получить довольно неплохую премию за импульс.»
> — *Gloss:* "Despite a very low Q1 (−11.52%), Q2–Q4 were even lower (−14.9%, −22.3%, −21.57%). So we did capture a decent momentum premium." → 2024 *live* year: Q1>Q2>Q3 but Q4 (−21.57%) slightly above Q3 (−22.3%) — another minor inversion, in live data this time.

The author's **own integrity standard** (ids 688, 693) demands the full quartile hierarchy be shown, not just Q1-vs-index — relevant because it frames why he insists on the clean ordering:

> **id 693 (2023-09-08):** «…Желательно наблюдать четкую иерархию доходностей выделенных групп. Идельно, когда доходность лучших > средних > худших. Допустимо, если, к примеру, доходность лучших > средних = худших…»
> — *Gloss:* "…You want a clear hierarchy: ideally best > middle > worst. Acceptable if e.g. best > middle = worst." → He explicitly tolerates a *flat* middle, which is what the pre-2024 chart had.

**Curve-fitting of the momentum formula over the full 2011→2024 sample** (directly bears on whether the early chart was optimized after the fact):

> **id 895 (2024-06-17):** «Немного попрактиковался в курвабобрфиттинге. А именно, в поиске такой комбинации моментума за разные периоды времени, которая максимизирует накопленную разность между Q1 и Q4. …лучший результат получился при использовании следующей формулы: (r(12-1)*a+r(6-1)*b)/СКО(12) … a = 0,9; b = 0,1.»
> — *Gloss:* "Practiced a bit of curve-fitting — searching for the momentum combination that **maximizes the cumulative Q1−Q4 spread**. Best result: (r(12-1)·a + r(6-1)·b)/STD(12), a=0.9, b=0.1." → The headline formula's coefficients were **chosen to maximize the cumulative Q1−Q4 spread** (self-described as curve-fitting).

> **id 898 (2024-06-23):** «…воспользоваться методом скользящего окна… Длина… 5 годами. Всего мы имеем 100 таких периодов. **Первый - с фев11 по фев16.** Второй - с март11 по март 16. И так до последнего периода, который начался в мае 2019 и закончился в мае 2024. …Комбинация a=0,9 b=0,1 набрала 95 баллов из 100…»
> — *Gloss:* "…use a rolling 5-year window… 100 such periods. **The first runs Feb-2011 → Feb-2016**, the second Mar-2011 → Mar-2016 … last is May-2019 → May-2024. The a=0.9/b=0.1 combo scored 95/100…" → **Confirms the backtest sample explicitly starts Feb-2011 and the formula was tuned across it.** The early years are part of the optimization target, not an independent out-of-sample stretch.

---

## Theme 4 — Survivorship / delisting handling for the early history

Documented, but as a **2024** improvement — implying the *earlier* version of the chart may have suffered survivorship/forward-looking bias the author was still removing in 2024.

> **id 858:** «…в том числе по тем, которые провели делистинг. Автовазы, Верофармы, Дорогобужи, энергосбыты не первой свежести - никто не должен уйти не посчитанным. Так мы если не устраняем полностью, то сильно уменьшаем **forward-looking bias**.»
> — *Gloss:* "…including delisted names — AvtoVAZ, Veropharm, Dorogobuzh, stale energy-sbyts — nobody uncounted. This **strongly reduces forward-looking bias** if not fully eliminating it." → He admits the bias was only *reduced*, not eliminated, even after the 2024 rework — and uses "forward-looking" (look-ahead) rather than "survivorship," but the delisted-inclusion intent is survivorship handling.

> **id 858 (splits caveat):** «Сплиты и "стирания лишних нулей" в ценах и дивидендах **не скорректированы**… Таких случаев немного: Фосагро в марте 2012, ИнтерРАО в январе 2015, Транснефть в феврале 2024 и НорНикель в апреле 2024.»
> — *Gloss:* "Splits and zero-stripping are **not adjusted** in prices/dividends… few cases: PhosAgro Mar-2012, InterRAO Jan-2015, Transneft Feb-2024, Nornickel Apr-2024." → Known un-corrected discontinuities in the early data; user of the published Excel must fix them manually. Relevant to early-chart accuracy.

No statement anywhere about how delisting/survivorship was handled in the **pre-2024** version of the chart. That remains undocumented.

---

## Most load-bearing message ids

- **852** — pre-2024-fix cumulative `Q2 < Q3`; the clean `Q1>Q2>Q3>Q4` is explicitly an outcome of the 2024 dividend-error fix.
- **858** — 2024 DB rebuild scope: broad-market "at-least-once members 2012–2024," delisted included (forward-looking-bias reduction), un-adjusted splits.
- **859** — reworked DB re-evaluates the whole Q1–Q4 history; mid-quartile returns shifted because of newly added names.
- **962** — universe choice (broad market) was decided by **pre-channel backtests** on three samples; mid/small caps deliberately retained.
- **895 / 898** — momentum formula coefficients curve-fit to maximize cumulative Q1−Q4 over a sample that **explicitly starts Feb-2011**.

## What is NOT in the export (state explicitly)

- No description of how the **original** (pre-May-2024) 2011–~2021 chart was constructed — data source, vendor, point-in-time index membership reconstruction, or survivorship method.
- No claim that the early chart is a contemporaneous live record (it cannot be — channel began Sept 2021; live quartile posts begin 2022).
- No use of the words реконструкция / задним числом / survivorship / выживаемость anywhere about his own series.
