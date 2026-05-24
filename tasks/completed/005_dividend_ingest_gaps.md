# Dividend ingest gaps — закрыть до бэкфилла цен

Phase 12 cross-check (`agent_context/dividends/reference_diff_report.md`) показал: **46 из 111 тикеров фейлят aggregate gate >20%**, у всех `Σours < Σlegacy`. После root-cause анализа — **часть расхождений by design, часть — реальные ингест-пропуски**.

Это **prerequisite перед task 006** (бэкфилл цен 2010-2013): нет смысла расширять историю на годы, где дивиденды дырявы — total return будет занижен.

## Root cause (исследовано)

### Категория А — «long-gap redomicile, не сшиваем» — **не в скоупе backfill**

Policy (set 2026-05-12, см. memory `project_bridge_policy.md`): сшиваем только короткие SECID-rename'ы (несколько дней разрыва, `iss_changeover` auto-seed), не сшиваем явно отмеченные `type=redomicile` в `data/tickers_manual.json` (X5, YDEX, HEAD, VKCO, MAIL — `old != new`).

**Bridged (cutoff=None, fill работает как у обычного тикера):**
- MTSI → MTSS (3 дня разрыв, iss_changeover) — MTSS prices с 2010-10 уже включают MTSI-era.
- EPLN → SFIN (5 дней, iss_changeover) — SFIN prices с 2015-12 уже включают EPLN-era.
- EONR → UPRO (1 день) — UPRO prices с 2014-06 уже включают EONR-era.
- TCSG → T (1 день) — T prices с 2019-10 уже включают TCSG-era.

**Not bridged (cutoff активен):** только записи в `tickers_manual.json` с `type=redomicile` и `old_secid != new_secid`. Это разрывы > года (NL→RU редомициляция X5/YDEX/HEAD/VKCO).

**Внешние сайты могут конфузить ticker namespaces** (research: dohod SFIN page титулована «ЭсЭфАй (Сафмар)», smart-lab SFIN содержит explicit строку `Тикер=EPLN`). Под bridge-политикой это **не проблема** — все EPLN-era записи валидны для SFIN. Но **для manual-редомицилей** (X5/YDEX) фильтр всё ещё нужен, иначе FIVE/YNDX-era попадут в новый эмитент.

```python
def predecessor_cutoff(ticker: str, tickers_manual: list[ManualEntry]) -> str | None:
    """Earliest valid registry_close for fill, or None.

    Returns max(renamed) across tickers_manual entries with:
      type=redomicile, new_secid==ticker, old_secid != new_secid.

    iss_changeover history is NOT a cutoff signal — see memory
    `project_bridge_policy.md`.
    """
```

### Категория Б — «old-history gap» — **реальные ингест-пропуски, в скоупе**

Тот же эмитент, ISS физически не отдаёт pre-2018 history. Проверено напрямую: `/iss/securities/MTSS/dividends.json` возвращает 13 строк с 2018-07-09, у legacy ещё 13 более старых записей 2010-2017 — их в ISS нет.

### Категория В — «recency lag» — мелочь, лечится повторным pull'ом

SFIN 2025-12 = 902 RUB declared 2025-11-21 — в наш предыдущий pull не успело. Лечится `momentum ingest dividends --tickers SFIN,...` перед backfill'ом.

## Storage policy (изменение архитектуры)

Текущий `data/.gitignore` держит `data/dividends/*` и `data/computed/monthly/*` вне репы — мотивация была «регенерируется из ISS». После 005 регенерация **больше не bit-deterministic относительно ISS**: часть записей приходит из dohod/smart-lab/legacy CSV, и эти источники со временем меняют верстку или исчезают. Чтобы pipeline оставался воспроизводимым без сети:

| Путь | До 005 | После 005 |
|---|---|---|
| `data/prices/{T}.jsonl` | gitignored | gitignored (regenerable из ISS, ~180 MB) |
| `data/dividends/{T}.jsonl` | gitignored | **committed** (~50 KB total, audit-trail) |
| `data/splits/{T}.jsonl` | gitignored | gitignored (regenerable из ISS) |
| `data/legacy/dividends_csv.jsonl` | n/a | **committed** (one-time CSV → JSONL, ~5K строк) |
| `data/computed/monthly/{T}.jsonl` | gitignored | **committed** (~18 MB, derived но stable) |
| `data/computed/curve_fit/q_values.jsonl` + holdings | committed | committed (без изменений) |

Обновляем `data/.gitignore` соответственно. Размер репы вырастет на ~20 MB — допустимо.

## Incremental compute mode

Текущий `compute_one()` всегда делает full rebuild monthly JSONL. После 005 — два режима:

- **Default (incremental):** `momentum compute monthly [--tickers ...]`
  - Читает существующий `data/computed/monthly/{T}.jsonl`.
  - Recompute последних `INCREMENTAL_RECOMPUTE_MONTHS` (default = 12, в `config.py`).
  - Append новые месяцы (после последнего существующего).
  - Pre-tail строки **не пересчитываются**, копируются as-is.
- **Full rebuild:** `momentum compute monthly --from-scratch [--tickers ...]`
  - Игнорирует существующий JSONL.
  - Используется ровно один раз после 005-backfill для затронутых тикеров, затем результат коммитится и становится новым baseline.
  - Также используется CI/первый clone, если `data/computed/monthly/` пустой.

### Safety gate (обязательно)

Incremental mode рискует molча разойтись с full-recompute если:
- Появился новый split на pre-tail диапазоне (multiplicative cascade двинет все pre-tail close_adj).
- Появился pre-tail dividend, не покрытый incremental окном.
- Изменилась формула в `monthly.py` без bump baseline.

Защита — **two-pass gate**:
1. После incremental compute сохранить sha256 hash от concatenated pre-tail rows (excluding last 12 months).
2. Сравнить с hash, сохранённым в `data/computed/monthly/_baseline_hashes.json` (committed).
3. Несовпадение → `raise ValueError("incremental drift detected for {T}; rerun with --from-scratch")`.

`--from-scratch` после прохода обновляет `_baseline_hashes.json` автоматически.

Это решает страх «старые monthly уедут после re-compute» детерминированно, без надежды на «само не сдвинется».

## Data sources (researched)

| Tier | Источник | URL | Coverage (verified 2026-05-12) | Парсер |
|---|---|---|---|---|
| 1 | **MOEX ISS** | `/iss/securities/{TICKER}/dividends.json` | 2018+ для большинства | already in pipeline |
| 2 | **dohod.ru** | `https://www.dohod.ru/ik/analytics/dividend/{ticker_lower}` | MTSS 2004+ (33 rec, 19 pre-2018), MGTSP 2004+ (15/12), MTLRP 2011+ (12/7), KRKNP 2012+ (14/6). **Weak**: PIKK (7/1), SFIN (10/1 — 2017-12 EPLN-era → filtered by cutoff). | `pd.read_html(html)[2]` → cols `[Дата объявления, Дата закрытия реестра, Год, Дивиденд]`, dates `DD.MM.YYYY`, decimal=`.` (точка не запятая в HTML). |
| 3 | **smart-lab.ru** | `https://smart-lab.ru/q/{TICKER}/dividend/` | MTSS 2017+ (15 rec). **Preferred shares (MGTSP, KRKNP, MTLRP) → HTTP 404** — нет страницы. | `pd.read_html(html)[0]` → header row 2: `[Тикер, дата T-1, дата отсечки, Период, дивиденд, Цена акции, Див.доходность]`. Amount c `₽` suffix (`35₽`), dates `DD.MM.YYYY`, decimal=`,`. **Filter by Тикер column** — записи с другим `Тикер` (предшественник) дропать. |
| 4 | **legacy CSV** | `raw_sources/Российские_акции_дивиденды.csv` → `data/legacy/dividends_csv.jsonl` | 2010-март 2026, monthly granularity. MTSS 26 months, MGTSP 9, SFIN 8 (включая EPLN-era 2017-12 → filtered), PIKK 5. | One-time CSV→JSONL ingest. **Layout: rows=months ("январь 2010"…), cols=tickers, sep=`;`, decimal=`,`, no thousand separators**. Inferred `registry_close = month-end last business day`, `registry_close_source = "inferred_month_end"`. Single value per cell (multi-payout уже просуммирован автором). |

**Slag-codepath ветвится по `registry_close_source`** (важно для task 006-era pre-2014 dividends):
- `iss / dohod / smartlab` (точная дата) → daily codepath: `(1-tax) × amt / close_pre_ex_day`.
- `inferred_month_end` → monthly codepath: `(1-tax) × amt / close(M-1)` (monthly-close предыдущего месяца). Используется когда daily prices до ex-date недоступны (pre-2014 после task 006).

**Зависимости:** `lxml` нужен `pd.read_html`. Добавить через `uv add lxml`. `beautifulsoup4` уже в venv (используется для smart-lab `Тикер`-фильтра до read_html, либо вообще вместо).

**Confirmed cross-source agreement**: MTSS 2010-05: legacy=15.4, dohod=15.4 ✓. MTSS 2018-07-09: ISS=23.4, dohod=23.4, smart-lab=23.4 ✓.

**Tier priority в `_merge()`**: ISS > dohod > smart-lab > legacy CSV. Dedup-key `(registry_close, amount, currency)`. Если две записи разных tier'ов имеют одинаковый key — выигрывает более высокий tier.

**Tier-4 month-sum suppress** (решает kpd: ISS `2018-07-09 23.4` vs legacy `2018-07-31 23.4` — одна выплата, разные даты, dedup-key не схлопывает → молчаливое удвоение TR). Перед `_merge()`:

1. Для каждого (ticker, calendar month, currency) собрать `Σ_high = Σ amount` по записям tier ≤3 в этом месяце.
2. Для legacy-записи (tier 4) с тем же (ticker, month, currency) и `amount = X`:
   - Если `Σ_high > 0` и `|X − Σ_high| / max(Σ_high, 0.01) < 0.01` (1% относительная, либо absolute < 0.01 RUB для копеечных) → **skip legacy**.
   - Иначе legacy уходит в `_merge()` с inferred month-end registry_close.

Корректно покрывает multi-payout кейсы (UPRO 2016: два tier-3 пейаута → их сумма совпадёт с tier-4 month-aggregate). НЕ покрывает кейс «два разных пейаута того же ticker в разных tier'ах не сошлись» — для этого есть phase 12 audit-diff.

## Scope (Категория Б — pre-flight verified 2026-05-12)

| Ticker | Σlegacy | Σours | diff % | Канонич | predecessor? | dohod | smart-lab | Note |
|---|---:|---:|---:|---|---|---|---|---|
| MTSS  | 439.1   | 272.6  | -37.91% | МТС | no | 19 pre-2018 | 0 pre-2018 | dohod fills |
| MGTSP | 1319.91 | 463.00 | -64.92% | МГТС-4ап | technical ISIN-rename only, no separate file | 12 pre-2018 | 404 | dohod fills |
| UPRO  | 2.525   | 0.872  | -65.45% | Юнипро | **EONR before 2016-07** | cutoff=2016-07-01 → 0 useful pre-cutoff | needs test | thin scope |
| MTLRP | 107.5   | 44.81  | -58.31% | Мечел ап | no | 7 pre-2018 | needs test | dohod fills |
| KRKNP | 13279   | 6505   | -51.02% | СаратНПЗ-п | no | 6 pre-2018 | 404 | dohod fills |
| PIKK  | 117.7   | 72.09  | -38.76% | ПИК | no | 1 pre-2018 | needs test | legacy CSV main (5 months) |
| LNZLP | 5989    | 3999   | -33.23% | Лензол. ап | no | needs test | needs test | TBD on impl |
| LEAS  | 162     | 104    | -35.80% | Европлан | no | recency, IPO 2024 | recency | recency-lag only (cat. В) |
| **SFIN**  | 1317.87 | 385.60 | -70.74% | ЭсЭфАй | **EPLN before 2018-01-03** | cutoff drops 1 record | smart-lab mixes EPLN explicitly | **moves to Cat. А** |

**Cat. А (predecessor not bridged — annotate, no fill):**
- Из manual: X5, YDEX, HEAD, VKCO (+ POLY/BELU marker-style — old==new, не predecessor).
- Из tickers.json history: T (←TCSG), SFIN (←EPLN), UPRO (←EONR), VKCO (дубль с manual).

**Pre-flight на оставшиеся «maybe» (надо проверить во время impl):**
- MDMG, GEMC, OZON — нет history-entry в tickers.json, нет в manual → **в скоупе fill**, но возможны другие предки.

**Замечание о применимости pre-2014 div к backtest:** для тикеров с ISS-prices, начинающимися с 2014, добавление 2010-2013 dividend-записей **не двинет ни одной строки** в `data/computed/monthly/{T}.jsonl` — они дропнутся в `monthly_total_returns()` как "before first price". Эти записи нужны только для (а) закрытия audit-gate в `legacy_dividends_diff.md` и (б) корректного total_return после task 006. Это **не баг**, это последовательность фаз.

## Implementation strategy

### Новый модуль: legacy CSV → JSONL

`src/momentum/ingest/legacy_dividends_csv.py`:

```python
def convert_csv_to_jsonl(csv_path: Path, out_path: Path) -> int:
    """One-shot: parse raw_sources/Российские_акции_дивиденды.csv into
    data/legacy/dividends_csv.jsonl. Returns row count.

    Output schema:
        {"ticker": str, "registry_close": "YYYY-MM-DD",  # inferred month-end
         "amount": float, "currency": "RUB",
         "source": "legacy_csv_monthly",
         "registry_close_source": "inferred_month_end"}

    CSV layout assumed: rows=tickers, cols=Russian month-year (e.g. "Май 2010"),
    cells = aggregate dividend in RUB for that month. Multiple payouts in same
    month already summed by CSV author.
    """
```

CLI: `momentum ingest legacy-dividends --csv-in raw_sources/Российские_акции_дивиденды.csv --out data/legacy/dividends_csv.jsonl`.

**One-shot operation.** После первой генерации `data/legacy/dividends_csv.jsonl` коммитится, `raw_sources/Российские_акции_дивиденды.csv` больше не читается pipeline'ом.

### Новый модуль: fill из internet sources

`src/momentum/ingest/dividends_fill.py`:

```python
class DohodFetcher:
    source_tag = "skill_fill_dohod"
    def fetch(self, ticker: str) -> list[dict[str, Any]]: ...

class SmartLabFetcher:
    source_tag = "skill_fill_smartlab"
    def fetch(self, ticker: str) -> list[dict[str, Any]]: ...

class LegacyCsvFetcher:
    """Reads pre-built data/legacy/dividends_csv.jsonl, no HTTP."""
    source_tag = "legacy_csv_monthly"
    def fetch(self, ticker: str) -> list[dict[str, Any]]: ...


def fill_dividends(ticker: str) -> list[dict[str, Any]]:
    if is_redomicile_target(ticker):
        LOG.info("skip %s — redomicile, predecessor dividends not bridged", ticker)
        return []
    existing = read_jsonl(Path("data/dividends") / f"{ticker}.jsonl")
    existing_keys = {_dedup_key(r) for r in existing}
    new_records: list[dict[str, Any]] = []
    for fetcher in (DohodFetcher(), SmartLabFetcher(), LegacyCsvFetcher()):
        for rec in fetcher.fetch(ticker):
            if _dedup_key(rec) in existing_keys:
                continue
            # Tier-suppress: if legacy_csv record falls within ±5 days
            # of an existing record with same amount → skip (it's the same payout).
            if fetcher.source_tag == "legacy_csv_monthly" and _has_nearby_match(rec, existing):
                continue
            new_records.append(rec)
            existing_keys.add(_dedup_key(rec))
    return new_records
```

`predecessor_cutoff(ticker)` (см. секцию Cat. А) — читает оба источника. Любая fetched-запись с `registry_close < cutoff` дропается. Если cutoff пустой и `fetched == []` для тикера — тоже не fill.

**Cache HTTP** (из memory feedback `cache_before_validate`): dohod/smart-lab HTML кешируется в `.fill_cache/{source}/{ticker}.html` до парсинга. Парсер падает → не теряем round-trip.

### Изменения в существующем коде

**`src/momentum/ingest/dividends.py`** — `VALID_SOURCES` расширяется:
```python
VALID_SOURCES = {"moex_iss", "skill_fill_dohod", "skill_fill_smartlab",
                 "skill_fill_disclosure", "manual", "legacy_csv_monthly"}
```

**`_merge()`** уже использует ключ `(registry_close, amount, currency)` — кросс-source дубликаты схлопнутся автоматически. Tier-priority обрабатывается в `fill_dividends()` до вызова `_merge()`.

**`src/momentum/compute/pipeline.py`** — `compute_one()` принимает `from_scratch: bool` параметр. При `from_scratch=False` (default):
1. Загрузить существующий `data/computed/monthly/{T}.jsonl`.
2. Найти последние `INCREMENTAL_RECOMPUTE_MONTHS` строк (хвост).
3. Recompute хвоста + всех месяцев после.
4. Сконкатенировать: pre-tail (as-is) + recomputed tail + new months.
5. Записать атомарно.
6. **Safety gate:** hash pre-tail (concat as JSON-strings, sha256) → сравнить с `_baseline_hashes.json[ticker]`. Mismatch → fail-loud.

**`src/momentum/config.py`** — добавить:
```python
INCREMENTAL_RECOMPUTE_MONTHS = 12
```

**Safety gate recovery workflow.** Если incremental ловит drift в pre-tail хеше:
1. CLI печатает diagnostic: `ValueError("drift detected for {T}: pre-tail rows N-{INCREMENTAL_RECOMPUTE_MONTHS} hash mismatch. Most likely a new split/dividend lands in pre-tail window. Inspect data/splits/{T}.jsonl and data/dividends/{T}.jsonl.")`
2. User проверяет diff → если drift expected (new split/div корректно обнаружен) → `momentum compute monthly --from-scratch --tickers {T}` rebless baseline.
3. `_baseline_hashes.json` обновлён, commit. Pipeline возвращается в incremental режим.

**`_baseline_hashes.json` структура:** один файл `data/computed/monthly/_baseline_hashes.json` с sorted keys (alphabetical by ticker). Schema: `{"TICKER": "<sha256>"}`. Merge-friendly (только append/update per ticker). Конфликты при параллельных `--from-scratch` для разных тикеров → trivial git resolve.

**`data/.gitignore`** — обновить:
```
prices/
indices/
splits/*
!splits/_acked.json
manifest.json

# computed/: monthly + curve_fit committed (frozen baseline + site data).
# simple/ — internal-only, gitignored.
computed/simple/
```
(удалить строки `dividends/*` + `computed/*` + `!computed/curve_fit/` и т.п.)

### Workflow (one-shot после 005-implementation)

1. `momentum ingest legacy-dividends --csv-in raw_sources/... --out data/legacy/dividends_csv.jsonl` → commit.
2. `momentum ingest dividends --tickers <all_failing>` → подтянуть recency lag из ISS.
3. `momentum ingest fill-dividends --tickers MTSS,MGTSP,SFIN,...` → augment `data/dividends/{T}.jsonl` из dohod/smart-lab/legacy.
4. `momentum compute monthly --from-scratch --tickers <affected>` → full rebuild для затронутых тикеров. Обновляет `_baseline_hashes.json` для этих тикеров.
5. `momentum compute backtest` → пересборка `data/computed/curve_fit/*` (q_values + holdings).
6. Регенерация `agent_context/dividends/reference_diff_report.md`.
7. Commit всех изменённых файлов в репу.

После 005 ежедневный rhythm: `momentum ingest dividends --tickers <new>` + `momentum compute monthly` (incremental по умолчанию) + `momentum compute backtest`.

## Тесты

- `tests/test_legacy_dividends_csv.py`: парсер CSV — russian month-year headers ("Май 2010" → 2010-05-31), blanks, thousand separators, multi-payout cells.
- `tests/test_dividends_fill.py` (mocked HTTP):
  - dohod.ru fetch корректно парсит table 2.
  - Tier-4 month-sum suppress: ISS `2018-07-09 23.4` + legacy `2018-07-31 23.4` (same month) → legacy skip'ается, в выходе одна запись с ISS-датой.
  - Multi-payout suppress: ISS `2016-05-10 1.0` + ISS `2016-05-25 1.5` + legacy `2016-05-31 2.5` → legacy skip'ается (Σ_high = 2.5).
  - Mismatch passes through: ISS `2018-07-09 23.4` + legacy `2018-08-31 18.0` (разные месяцы) → обе записи в выходе.
  - Redomicile gate: `fill_dividends("X5")` возвращает `[]` без HTTP-запросов.
  - Last-resort: если оба external = empty, читает `data/legacy/dividends_csv.jsonl`.
- `tests/test_dividends.py` — `VALID_SOURCES` расширен, новый enum `legacy_csv_monthly` проходит валидацию.
- `tests/test_pipeline_incremental.py` (новый):
  - Default incremental: existing JSONL с 100 строками + новый месяц прайсов → output 101 строка, первые 88 (100-12) бит-идентичны входу.
  - `from_scratch=True`: 100 строк full-rebuild, idempotent (повторный прогон даёт identical output).
  - Safety gate fail: подменить close_adj в pre-tail сырых прайсов → incremental detect drift → ValueError.
  - Safety gate pass: только новый месяц прайсов добавлен → no drift, output корректный.

## Acceptance

1. `data/legacy/dividends_csv.jsonl` — committed, ~5K строк, парсер покрыт тестами.
2. `data/dividends/{T}.jsonl` — committed для всех ~1000 тикеров, ~50 KB total.
3. `data/computed/monthly/{T}.jsonl` — committed для всех тикеров, ~18 MB total. Содержит `_baseline_hashes.json` рядом.
4. `agent_context/dividends/reference_diff_report.md` перегенерирован: **aggregate fails 46 → ≤20** для тикеров Категории Б. Тикеры Категории А (redomicile) остаются «fail» — это by design, отдельная секция.
5. В отчёте отдельная секция «Redomicile predecessors — divergence by design» перечисляет X5/YDEX/HEAD/VKCO/T/etc. с пояснением.
6. `data/dividends/{TICKER}.jsonl` для целевых тикеров содержит записи с `source ∈ {skill_fill_dohod, skill_fill_smartlab, legacy_csv_monthly}`.
7. `momentum compute monthly` (без флага) на чистом репо после fresh clone работает incremental: первый запуск = full (нет существующего JSONL), второй запуск = no-op (нет новых данных).
8. `momentum compute monthly` с подменёнными pre-tail input'ами (новый split в 2018) **падает с ValueError**, не молча портит monthly.

### Phase 12 re-verification (обязательно после реализации)

005 трогает дивиденды + меняет compute-режим → перепроверить, что цены и квантильная разбивка не уехали:

- `.venv/bin/python -m pytest -q` — **все тесты зелёные**. Особенно:
  - `tests/test_momentum_examples.py` (VSMO anchor 4.6458%) — должен остаться зелёным (дивы не входят в r(12-1)).
  - `tests/test_author_quantiles.py` (Jaccard на 2026-03-31) — пороги Q1/Q4 ≥ 0.5, Q2/Q3 ≥ 0.3 сохраняются. Допустимо: Jaccard может слегка вырасти (новые дивы → корректнее total return → точнее ранжирование). Падение > 0.05 — flag, расследовать.
- `agent_context/author_quantiles_diff.md` — перегенерировать.
- `agent_context/legacy_prices_diff.md` — перегенерировать. **Должен быть бит-в-бит идентичен** (мы цены не трогали). Если изменился — непреднамеренная регрессия.
- `agent_context/dividends/reference_diff_report.md` — главный артефакт, пересобрать обязательно.
- **Incremental-mode проверка:** на тикере без новых дивов прогнать `momentum compute monthly --tickers SBER` (incremental) → diff с pre-existing JSONL = 0 строк. На тикере с новой div (например, MTSS) → diff > 0, только новые/исправленные строки.

Если что-то уехало в неожиданном направлении — **не закрывать 005**, разбираться.

## Не входит

- Бэкфилл цен 2010-2013 (task 006 — после 005).
- Сшивка дивидендов через редомициль (выходит за политику pipeline — см. methodology).
- Восстановление дивидендов делистнутых тикеров (отдельный issue).
- USD-дивидендов RUAL/POLY (out-of-scope by design).
- Phase 13 skill UX-обёртка (отдельная задача, переиспользует ядро `dividends_fill.py`).
- Коммит `data/prices/` или `data/splits/` — они gitignored остаются (regenerable из ISS, объём слишком большой).

---

## Postmortem (added 2026-05-12, post-closure cleanup)

После закрытия 005 в той же сессии пайплайн был дополнительно почищен — изменения **противоречат части plan'а выше**, актуальное состояние:

### CSV-as-source отменён
Hand-compiled CSV (`raw_sources/Российские_акции_дивиденды.csv`) **не источник** в production. Tier 4 (`legacy_csv_monthly`) вырезан целиком:
- удалены `src/momentum/ingest/legacy_dividends_csv.py`, `tests/test_legacy_dividends_csv.py`
- удалены: `LegacyCsvFetcher`, `_suppress_tier4_month_sum`, `_date_tol_for(legacy)`, `n_tier4_suppressed`, source priority `legacy_csv_monthly: 30`
- CLI `ingest legacy-dividends` убрана, `ingest fill-dividends --sources` дефолтит `dohod,smartlab`
- universe-wide cleanup: `legacy_csv_monthly`-записи дропнуты из всех `data/dividends/*.jsonl` (4 записи в 3 файлах — большинство уже dedup'нуло раньше)
- raw CSV + parser + audit scripts (`compare_dividend_sources.py`, `screen_iss_anomalies.py`, `regen_legacy_dividends_diff.py`) переехали в `validate_with_raw/` (gitignored). Парсер сохранён там же как `legacy_dividends_csv_to_jsonl.py` чтобы JSONL был воспроизводим
- `data/legacy/` удалён, `data/.gitignore` без legacy-секции

### Final audit state
`validate_with_raw/legacy_dividends_diff.md`: **0 FAILs / 107 тикеров** (vs 46 в Phase 12). 

### Conflict-resolved расширен с 4 до 28 записей через round-2 + round-3 research
Покрытые patterns:
- **stale half-figure** (board pre-rec → revised): MTLRP 2017, LSRG 2017, SELG 2019 — `replace`
- **stale pre-approval revised before EGM**: SFIN 2024 — `drop`
- **missing AGM tranche** (2 events same registry): VSMO 2023 augment, MFON 2014/2016 augment
- **missing interim tranche** (semi-annual lag): DATA 2025, AKRN×2, AVAN×2, LEAS, MDMG, NKHP×2, PLZL×2, BSPBP — augment from disclosure
- **same-payout date-shift dup**: HIMCP 2018 (ex vs payment date) — drop
- **board-rec date dup** (ISS double-counts): NKNC 2020, NKNCP 2020, KZOS 2020, KZOSP 2020, MOEX 2023 — drop
- **stale half-figure variant**: PHOR 2023 (ISS 216, dohod 264 правда) — drop
- **smart-lab data error**: PHOR 2022 фантом 390 — drop
- **pre-IPO phantom**: EUTR 2023-07 (IPO был 2023-11) — drop

### CONFLICT_ACTIONS расширен до `{replace, drop, augment}`

### Smart-lab — окончательный вклад
**4 продакшен-записи во всём universe** (PHOR 2015-2017 мелкие interim). По prefs смартлаб принципиально 404 (нет страниц). Третий cross-check канал оправдан (поймал PHOR-смартлаб-фантом 2022-10-03 на final-Q registry), материальный вклад маргинальный. Решение убрать/оставить — в новой задаче после task 006.

### Tests: 255 → 245 (10 удалены вместе с legacy CSV кодом)
