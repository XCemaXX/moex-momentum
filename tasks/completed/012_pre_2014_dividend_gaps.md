# Pre-2014 dividend gaps — multi-source unified ingest

## Контекст

После task 005 (initial fill: ISS + dohod + smartlab + disclosure) production
содержит 99 pre-2014 dividend records (77 от dohod, 22 от ISS). Legacy CSV
`validate_with_raw/dividends_csv.jsonl` имеет 307 pre-2014 записей по 89 тикерам,
из них **205 записей по 59 тикерам не покрыты ни одним production-источником**.

ISS dividends endpoint имеет hard cutoff ≈2013-2014 на любом доступном пути
(основной `/securities/{S}/dividends.json` без board-параметра,
`/history/.../dividends.json` 404, predecessor-SECID возвращает 0 rows). В отличие
от prices (task 006) данные физически отсутствуют в ISS API — board-union /
predecessor-iteration не помогут.

## Discovery log (2026-05-15..16)

Подробный обход всех известных источников. Все источники проверены empirically
с прямыми HTTP-запросами или агентами.

### ✗ smart-lab.ru — redundant tier-3

Discovery-agent verdict 2026-05-16 (raw probe-files в `/tmp/smartlab_probe/`):

- `/q/{TICKER}/dividend/` per-payment HTML-таблица server-side truncated до
  ~11 последних строк. **Earliest год = ~2017** (LKOH per-payment min=2017-09;
  LNZL min=2017-07). Pre-2017 в per-payment виде НЕТ.
- Embedded JS-variable `aYearSeries` = JSON object
  `{"xaxis":[years...], "dividend":[amounts...], "div_yield":[...], "dividend_pr":[...]}`.
  Для LKOH покрывает 2000-2025 (26 лет). **Yearly aggregate без per-payment
  дат и без splits granularity** — нельзя merge в нашу per-payment JSONL схему
  (dedup key требует `registry_close`).
- `/dividend` и `/dividend/` **byte-identical** — trailing slash carries
  zero info, сервер нормализует. Юзерская подсказка про без-слеша noise.
- Pref-URL `/q/LNZLP/dividend/` → 404. Common-share URL `/q/LNZL/dividend/`
  отдаёт обе share-classes одной таблицей (колонка `Тикер`).
- `?page=2`, `?all=1`, `/dividend/all/`, `/dividend/2010/` — все вернули ту
  же truncated HTML. AJAX/XHR нет, pure SSR.
- Pastebin `N3G4fupa` parser: trivial `pd.read_html` last-matching-table,
  использует колонку `дата T-1` (cum-div date), не `дата отсечки` (registry).
  Наш текущий fetcher использует `дата отсечки` — правильнее (matches
  ISS/dohod semantics).
- Production smartlab fetcher (`src/momentum/ingest/dividends_fill.py:333-426`)
  дал только 4 записи на universe (PHOR 2015-2017). **Три бага**:
  1. `pd.read_html(..., header=1)[0]` берёт первую таблицу — но если на
     странице есть «Ожидаемые» (forecast) таблица, она первая, paid идёт
     вторым. Pastebin использует `[-1]` — тоже brittle при добавлении
     trailing-таблиц. Правильно — filter по class `sort-table` AND отсечь
     те у которых caption/th содержит «Ожидаемые».
  2. Pref→common SECID mapping не сделан. `/q/LNZLP/dividend/` → 404,
     silent zero records. Map должен быть LNZLP→LNZL, MGTSP→MGTS, KRKNP→KRKN,
     SNGSP→SNGS, RTKMP→RTKM, etc.
  3. `aYearSeries` JSON игнорируется — а это единственный путь к pre-2017
     данным на smartlab. Но это только yearly aggregate, не годится для
     per-payment merge.
- **Verdict**: даже пост-фикса всех трёх багов, smartlab per-payment отдаст
  **0 unique records** vs Yahoo+tbank+dohod+ISS — full overlap на 2017+
  диапазоне. `aYearSeries` 2000-2024 — единственное durable-уникальное, но
  только как annual-aggregate sanity check, не backfill. **Smartlab → archive
  в `dividends_backfill/` после Phase 5**, либо лёгкий cross-check helper
  читающий aYearSeries для validation report.

### ✗ mfd.ru — дивидендов нет вообще

- Info-page `/marketdata/ticker/?id={mfd_id}` для LNZLP (id=14995) — 0 mentions
  «дивиденд».
- Главная `/`, `/marketdata/`, `/marketdata/company/description/?id=...` — 0
  dividend-related ссылок (`grep` по `href=*div*`).
- Архитектурно — price/news/forum aggregator. Гипотеза task 014 («mfd как
  4-й dividend tier») окончательно опровергнута. Mfd как dividend-tier
  **не реализовывать**.

### ✗ investing.com — Cloudflare-walled

- `POST www.investing.com/equities/MoreDividendsHistory?pairID=...&last_timestamp=...`
  отдаёт HTML-fragment с 6 rows/page, нужен walk-back через `last_timestamp`.
- **Cloudflare блокирует после 3-6 запросов** на одном IP. Известная проблема,
  не работает уже ~2 года.
- `api.investing.com/api/financialdata/{pairId}/historical/chart/` — это
  prices-endpoint (chart), не dividends.
- Альтернатив-обёртки community (investpy, investiny, defeatbeta-api) или
  отказались от dividend endpoint, или требуют `curl_cffi` (TLS-fingerprint).
- Mapping MOEX SECID → investing pair_id тоже через Cloudflare-walled
  `search/service/SearchInnerPage` endpoint.
- Для 28 тикеров × 4 страницы = 112 sequential requests — невозможно без
  heavy browser-automation. **Отвергаем без специальных tools.**

### ⚠ investfunds.ru — URL pattern сменился, mapping не решён

- Article 2017 (habr 345696) использовал `/stocks/{numeric_id}/dividend/` —
  работает для legacy/delisted (AVAZ id=3 → дивиденды 2003-2023, 17 дат).
- Modern big-cap: `/stocks/Rosneft/dividend/`, `/stocks/Lukoil/dividend/` и т.д.
  возвращают 200 с placeholder-homepage (не реальная dividend-страница).
- `emitents_id` из JSON-каталога (ROSN=123, LKOH=128) ≠ stock_id для URL path
  (`/stocks/123/` для ROSN → 404).
- **Не доведено до конца** — настоящий stock_id mapping в JSON-каталоге под
  каким-то другим ключом, но diminishing-returns. Не приоритет.

### ✓ Tinkoff (tbank.ru SPA-bootstrap) — depth неоднородна, но реально глубокая

- SPA-bootstrap `www.tbank.ru/invest/stocks/{T}/dividends/` отдаёт
  `<script type="application/json">` с `stores.investDividends[T].dividends`,
  поля `{reestr, dividend.value, dividend.currency}`.
- Anonymous, без auth/cookies, один GET, payload ~700 KB.
- **Phase 2 bulk-pull (2026-05-16)**: 310/1029 OK, 719 not_found, 0 transient.
  Кэш 395 MB в `.fill_cache/tbank/`.
- **Depth опровергнут ранний вывод «~2017»**: Phase 2 показала **39 тикеров с
  pre-2010 records**, earliest **MSNG 1998-04-10**. INGR 45 записей с 1998,
  AFLT 1999, RTKM 1998, TATN 2004. SPA-bootstrap отдаёт значительно глубже чем
  mobile app — user-spot-check ROSN/LKOH в приложении (показал только 2017+)
  был misleading: глубина per-ticker неоднородна. Большинство ROSN/LKOH-class
  крупняка действительно отрезано на 2013-2017, но historic тикеры с долгой
  историей идут на десятилетия назад.
- **Tinkoff — primary tier для pre-2014 residual** наравне с Yahoo. Phase 2
  cascade: Yahoo winner для 93 тикеров pre-2014, Tbank winner для 47 — суммарно
  140/152 тикеров с pre-2014 контентом закрыты этими двумя.

### ✓ Yahoo Finance v8 chart API — **breakthrough**

- `query1.finance.yahoo.com/v8/finance/chart/{T}.ME?events=div&period1=...&period2=...&interval=1d`
- Anonymous (без crumb/cookie для chart endpoint), один GET, payload ~300 KB.
- Schema: `chart.result[0].events.dividends = {unix_ts: {amount, date}, ...}`,
  meta currency=RUB, **split-adjusted** (нет GMKN-style ×100 артефакта).
- Mapping: MOEX SECID + `.ME` suffix → Yahoo symbol. Подтверждено на 14 тикерах.
- **Date semantic = ex-dividend date** (~3-7 business days до registry-close,
  который дают ISS/dohod/tbank). Нужно tag'ить как `registry_close_source:"yahoo_ex_div"`.
- Live-probe от 2026-05-16, кэш в `.fill_cache/yahoo/{T}.json` для 14 high-impact
  тикеров (LKOH/LNZLP/VTBR/TATN/TATNP/BSPB/MSRS/SIBN/TRNFP/TGKA/MAGN/GMKN/SBER/MOEX):

  | Ticker | Yahoo records | earliest | pre-2014 | vs Tinkoff |
  |---|---|---|---|---|
  | LKOH | 31 | 2010-05-11 | 6 | Tinkoff: 2013-08 |
  | LNZLP | 21 | 2010-05-21 | 9 | Tinkoff: 20 records 2010+ |
  | VTBR | 13 | 2010-04-19 | 4 | Tinkoff: 2017-05 |
  | TATN | 29 | 2012-05-11 | 2 | partial (CSV хотел 4) |
  | TATNP | 35 | 2008-05-13 | 7 | ✓ |
  | BSPB | 21 | 2010-03-11 | 5 | ✓ |
  | MSRS | 19 | 2010-05-18 | 4 | ✓ |
  | SIBN | 29 | 2010-05-17 | 6 | ✓ |
  | TRNFP | 17 | 2010-05-31 | 4 | ✓ |
  | TGKA | 12 | 2010-05-13 | 4 | ✓ |
  | MAGN | 26 | 2010-04-05 | 3 | ✓ |
  | GMKN | 25 | 2010-05-24 | 5 | ✓ |

  Cross-check LNZLP 2018+ матчит production побайтово (8.71, 110.00, 13.87,
  3699.27, 5.29, 131.00, 21.42, 9.55), отличие только в дате на 1-4 дня (ex-div
  vs registry-close).

- **Yahoo закрывает 12/13 high-impact residual** тикеров. URKA → 404
  (delisted, нигде нет).

### ✗ URKA, VZRZ — truly delisted

- URKA (Уралкалий, delisted 2018): tbank 404, Yahoo 404, investing.com скорее
  всего тоже. **Acked-no-div для 2010-2013, как class исключения.**
- VZRZ (Возрождение, delisted 2018): tbank 404. Не пробован Yahoo, ожидается то же.

### не пробовано

- **Alor / Finam APIs** (habr 927238): аналогичный official-broker model как
  Tinkoff. Требуют брокерский счёт + token + SECID → broker-internal-id mapping.
  Coverage гипотетически идентичен Tinkoff (источник = MOEX/НРД, не сам брокер).
  Не приоритет.
- **e-disclosure.ru** (квартальные отчёты эмитентов через XBRL/PDF). Heavy
  parser. Не приоритет пока Yahoo+Tinkoff закрывают.
- **investfunds.ru deep mapping** — см. выше, не решено.

## Design decisions (locked)

Утверждено юзером 2026-05-16:

1. **Date conflict resolution**: keep priority-source date + tag origin через
   новое поле `registry_close_source` со значениями:
   `iss | dohod | yahoo_ex_div | tbank_reestr | smartlab_t1`.
2. **Merge strategy**: pure cascade `ISS → dohod → Yahoo → tbank → smartlab`,
   первый источник где есть запись побеждает. Конфликты (overlap с разными
   amounts) логируются в `data/dividends/_conflicts_resolved.json`.
3. **Refactor timing**: subpackage `src/momentum/dividends/` создаётся **перед
   Phase 2** (= после Phase 1 smartlab discovery, перед bulk pull).
4. **Phasing**: pause после Phase 2 (per-source coverage report) и Phase 4
   (CSV gap report) для review.
5. **CSV** — purely validation source, **никогда не ингестим**.
6. **Raw cache mandatory** в `.fill_cache/{source}/{TICKER}.{ext}` (по правилу
   memory `feedback_cache_before_validate`).
7. **Validation scripts** в `validate_with_raw/`.

## Plan (phases)

### Phase 1 — Smartlab discovery [DONE 2026-05-16]

Agent отработал, raw в `/tmp/smartlab_probe/{ROSN,LKOH,SBER,LNZLP,AKRN,LNZL}_{noslash,slash}.html`,
pastebin parser в `/tmp/smartlab_probe/_pastebin_parser.txt`, summary
`/tmp/smartlab_probe/_summary.json`.

Verdict (см. Discovery log выше): per-payment usable только 2017+ (full
overlap с tbank/Yahoo/ISS), aYearSeries 2000+ — yearly aggregate без дат
(несовместим с per-payment merge). Smartlab **не даёт unique records** для
backfill — pre-2017 как per-payment там физически нет, post-2017 уже покрыто
другими источниками.

Решение: smartlab fetcher удалён целиком в Phase 1.5 (не архивирован — нет
unique contribution, нет смысла хранить даже в backfill-папке). Tag
`skill_fill_smartlab` остаётся в `SOURCE_PRIORITY` и `VALID_SOURCES` для
4 legacy PHOR-записей 2015-2017 в `data/dividends/PHOR.jsonl` — они дедупнутся
естественно через cascade dohod/yahoo/tbank в Phase 3.

### Phase 1.5 — Refactor `src/momentum/dividends/` [DONE 2026-05-16]

Сделано:
- `src/momentum/ingest/dividends.py` → split:
  - `src/momentum/dividends/iss.py` (ISS ingest + `_merge`)
  - `src/momentum/corporate/dividend_gaps.py` (`compute_gaps`, `load_acked`,
    `save_gaps` — переехало в `corporate/` потому что соединяет prices×dividends,
    компаньон `corporate/detect.py`).
- `src/momentum/ingest/dividends_fill.py` → split:
  - `src/momentum/dividends/dohod.py` — DohodFetcher
  - `src/momentum/dividends/merge.py` — `dedup_near_duplicates`, `cleanup_jsonl_near_duplicates`
  - `src/momentum/dividends/fill.py` — `Fetcher` Protocol, `predecessor_cutoff`,
    `fill_dividends`, `FillResult`
  - `src/momentum/dividends/conflicts.py` — `apply_conflicts_to_jsonl`,
    `apply_conflicts_to_universe`, `_load_conflicts`
  - `src/momentum/dividends/types.py` — `DedupKey`, `dedup_key`, `SOURCE_PRIORITY`
    (+ entries для `skill_fill_yahoo=65`, `skill_fill_tbank=63`), `VALID_SOURCES`,
    `CONFLICT_ACTIONS`.
- Удалено: `SmartLabFetcher` (95 LOC) целиком. CLI default `--sources
  dohod,smartlab` → `dohod`. Тесты для smartlab fetcher (2) удалены, stub-source
  tags в других тестах переписаны на `skill_fill_yahoo`.
- Stub'ы для Phase 2: `src/momentum/dividends/yahoo.py`, `tbank.py` — пустые
  модули-плейсхолдеры.
- Imports обновлены: `src/momentum/cli.py` (3 сайта), `tests/test_dividends_iss.py`
  (новый, из старого `test_dividends.py`), `tests/test_dividend_gaps.py` (новый),
  `tests/test_dividends_fill.py` (rewrite), `validate_with_raw/screen_iss_anomalies.py`.
- `validate_with_raw/compare_dividend_sources.py` помечен note'ом — он был
  broken pre-refactor (LegacyCsvFetcher не существует), не активный, не чинил.

Всего: 248/248 тестов зелёные. Ruff/mypy: те же ошибки что и pre-refactor
(скопированные verbatim), новых не ввели.

### Phase 2 — Bulk pull [DONE 2026-05-16]

Fetchers: `src/momentum/dividends/{yahoo,tbank}.py`. Bulk-pull scripts:
`scripts/fetch_yahoo_dividends.py`, `scripts/fetch_tbank_dividends.py`.
Rate-limit 2 req/s, idempotent (skip if cache file exists, failures NOT
cached so re-run automatically retries).

Wall time ~10 мин каждый (запущены параллельно как background jobs).
Результаты:

| Source | OK | 404 | empty/no_payload | net_err | Cache |
|---|---:|---:|---:|---:|---:|
| Yahoo | 185 | 764 | 80 | 0 | 65 MB |
| Tbank | 310 | 719 | 0 | 0 | 395 MB |

Zero transient errors — re-run не нужен. Все failures permanent (тикер
отсутствует у источника / в данных).

Coverage report → `validate_with_raw/source_coverage.md`. Headline:
- **245/307 CSV pre-2014 записей закрыты** (80%).
- 62 still open, top: URKA(6), DGBZP(4), **VTBR(4)**, GLTR(4), GMKN(4), TRNFP(4).
- Pre-2014 cascade winners: Yahoo 93 тикеров, Tbank 47, ISS 6, dohod 6.
- 877/1029 тикеров pre-2014 нет вообще — модерн листинги (norm).

Discovery side-findings (см. Discovery log → Tinkoff section):
- Tbank reality глубже чем считали — 39 тикеров с pre-2010, MSNG с 1998.
- VTBR unit-mismatch CSV vs Yahoo (×4900 ratio) — задача для агента-research
  (отдельно), вердикт ожидается для уточнения cascade priorities.

ISS bug fix-up:
- `data/dividends/_conflicts_resolved.json` — 2 новых drop-entry для
  `2111-01-01` placeholder в PRIM и NPOF.
- `data/dividends/{PRIM,NPOF}.jsonl` — записи удалены idempotent apply.

### Phase 3 — Merge с cascade

- Реализовать `src/momentum/dividends/merge.py` с pure cascade
  ISS → dohod → Yahoo → tbank → smartlab.
- Dedup key: `(year-month bucket, amount ±0.5 RUB OR ±1% от amount)` для
  cross-source same-payment. Date-resolution: оставляем priority-source date.
- Conflict log: `data/dividends/_conflicts_resolved.json` с `{ticker, ym,
  primary_source/date/amount, conflicting_sources: [...]}`.
- `momentum compute monthly --from-scratch` + `backtest`.
- Inspection of mass-drift warning (новая из task 006 — должна срабатывать).

### Phase 4 — CSV cross-check [PAUSE FOR REVIEW]

- Regenerate `validate_with_raw/legacy_dividends_diff.md` после merge.
- Новый отчёт `validate_with_raw/csv_gap_report.md`:
  - Per-ticker таблица: CSV records НЕ в нашем merge → ticker, date, amount,
    `searched_in: [yahoo, tbank, smartlab, dohod, iss]`, verdict (acked /
    investigated).
  - Per-source breakdown: какой источник закрыл сколько CSV-gap records.
- **PAUSE**: юзер смотрит, решает acked-skip vs дальше копать.

### Phase 5 — Source redundancy analysis

Per-source: `unique records contributed` = records которые есть только в этом
источнике, не в любом более высоком приоритете.

Threshold: если source даёт <10 unique records на universe → candidate для
archive.

Smartlab уже удалён в Phase 1.5. Для dohod/tbank/yahoo: если кто-то после
фактического pull окажется ≤10 unique → archive в `dividends_backfill/`
parallel `mfd_backfill/`. Если все ≥10 → оставляем, документируем contribution
каждого.

### Phase 6 — Cleanup & docs

- `docs/methodology.md` секция «Dividend sources» с per-source описанием +
  каскад.
- `agent_context/dividends/sources_audit.md` с финальным per-source verdict
  (для будущего себя).
- Move task 012 в `tasks/completed/`.

## Acceptance

- Yahoo + tbank fetchers в production, source-tags `skill_fill_yahoo` /
  `skill_fill_tbank` в VALID_SOURCES.
- Smartlab: keep если pulls unique records >0, иначе archive в
  `dividends_backfill/`.
- All sources merged via cascade, `_conflicts_resolved.json` content
  per-ticker.
- Pipeline `momentum compute monthly --from-scratch` + `backtest` зелёные,
  test_momentum_examples VSMO=4.6458% intact.
- CSV gap report показывает residual (URKA + similar delisted) как acknowledged
  unrecoverable.
- All raw caches под `.fill_cache/{source}/`, validation scripts в
  `validate_with_raw/`.
- `docs/methodology.md` обновлён с описанием dividend sources cascade.

## Не входит

- investfunds.ru deeper investigation (URL mapping не решён, не приоритет).
- investing.com via curl_cffi / browser automation.
- Alor / Finam APIs (требуют брокерский счёт, гипотетический outcome — same
  coverage как Tinkoff).
- e-disclosure.ru XBRL parser (heavy, отложено).
- mfd.ru dividend tier (dead).
- Pre-2010 расширение (тот же класс проблемы, отдельный кейс).
- Address-rewrite task 014 — она помечена stale, отдельная переработка.

## Pinned memory & references

- `feedback_cache_before_validate` — raw HTTP fetches в cache до validation.
- `feedback_network_failures` — на timeout escalate, no retry-loops.
- `feedback_research_review` — research phases pause for user review.
- `project_pipeline_cadence` — one-shot historical → `scripts/`; monthly delta
  → `src/momentum/`. Subpackage `src/momentum/dividends/` подпадает под второе.
- `reference_isin_secid_sources` — fallback order для ISIN-резолва (применимо к
  Yahoo `.ME` mapping verification).

## Files touched / state snapshot

- `.fill_cache/yahoo/` — 14 JSON-файлов (LKOH, LNZLP, VTBR, TATN, TATNP, BSPB,
  MSRS, SIBN, TRNFP, TGKA, MAGN, GMKN, SBER, MOEX). URKA пытался, 404.
- `/tmp/tbank_div_cache/` — 58 HTML-файлов с прошлой сессии (residual gap
  tickers). НЕ committed, regenerable.
- `/tmp/smartlab_probe/` — 11 HTML-файлов + pastebin parser + summary JSON
  (Phase 1 raw). Verdict ✗ (см. Discovery log).
- `validate_with_raw/dividends_csv.jsonl` — ground-truth CSV (gitignored).
- `tasks/todo/014_mfd_dividends_and_storage_decision.md` — помечена stale в
  шапке, ждёт rescope.
