# Post-refactor follow-ups

> Создана 2026-05-19. Сюда выносятся пункты из «Out of scope» task 014 — не блокируют рефактор, делаются после него по мере необходимости.

## Context

Task 014 (structure refactor + CSV storage + flat src/) фокусируется на core structural changes. Следующие улучшения помечены как desirable, но не critical для self-sufficient repo. Каждый пункт — отдельная мини-задача.

## Items

### 1. Fetcher protocol unification

Сейчас `src/ingest/dividends/dohod.py`, `tbank.py`, `yahoo.py` каждый реализует свой fetch+parse независимо — нет общего интерфейса. Ввести `Protocol` (или `ABC`) `DividendFetcher`:

```python
class DividendFetcher(Protocol):
    name: str
    def fetch(self, secid: str) -> list[Record]: ...
```

Общий cache layer (after item 2 consolidation), общий error/retry policy. Снизит дублирование, упростит добавление нового источника (например, если откроется gold-standart 4-й tier).

### 2. `validate_with_raw/` — навести порядок (user-driven, НЕ удалять без отмашки)

Раз-валидация **не закончена** (см. task 017), папка остаётся активной. Задача — не «удалить», а сгруппировать и сохранить нужное. Реорг/удаление — только по явной команде пользователя.

Аудит на 2026-05-20 (808K, ~40 файлов):
- **Tooling (.py, переиспользуемое):** aggregate_wave_findings, compare_dividend_sources, phantom_dividend_scan, screen_iss_anomalies, source_coverage, regen_csv_gap_report, regen_legacy_dividends_diff, legacy_dividends_csv_to_jsonl.
- **Wave-находки (16):** wave1_agent1..5, wave2_agent6..10, wave3_agent11..15, wave4_agent16.
- **Staged → `_conflicts_resolved.json`:** wave_augments_staged (204), wave_acknowledged_staged (30), wave_dropped_findings (7).
- **Входы/референс:** dividends_csv.jsonl (264K), phantom_dividends.json (199), csv_gap_cells.json, legacy_gap_acknowledged.json (47), screening_muted.json.
- **Отчёты (.md):** dividend_source_comparison, iss_stale_screening, legacy_dividends_diff, csv_gap_report, source_coverage, cascade_dryrun.
- **Транзиентное:** `__pycache__/`, cascade_conflicts.json (пусто) + cascade_dryrun.md (пересоздаёт cascade-скрипт).

**Статус применения:** из 204 staged-augments 186 уже в `_conflicts_resolved.json`, **18 ещё нет** → staged НЕ полностью применён, удалять нельзя.

**Реорг сделан 2026-05-20.** Структура:
- корень: 8 `.py` скриптов (оставлены здесь — `parents[1]` = repo root).
- `waves/`: 16 wave*_agent* + 3 *_staged/dropped.
- `inputs/`: dividends_csv.jsonl, phantom_dividends, csv_gap_cells, legacy_gap_acknowledged, screening_muted.
- `reports/`: все .md + cascade_dryrun.md/cascade_conflicts.json.

Пути в скриптах + cascade (`REPORT_MD`/`CONFLICTS_JSON`) обновлены под подпапки. `aggregate_wave_findings.py` гоняется, cascade dry-run пишет в `reports/`.

**CSV-порт скриптов сделан 2026-05-20.** 5 скриптов переведены с `.jsonl`/`read_jsonl` на `read_records(... casts=...)` + поправлены устаревшие `momentum.*` импорты (→ `ingest`/`storage`/`config`, top-level `tickers`): `regen_legacy_dividends_diff`, `regen_csv_gap_report`, `phantom_dividend_scan`, `source_coverage`, `screen_iss_anomalies`. Прогнаны на committed CSV (screen — import-check, ему нужна сеть). Легаси `inputs/dividends_csv.jsonl` остаётся jsonl (читается inline `json`).

`compare_dividend_sources.py` НЕ портирован — он сам себя помечает как abandoned (ссылается на несуществующие `SmartLabFetcher`/`LegacyCsvFetcher`, сломан ещё до task 012). Переписывать только если понадобится.

**Остаток (user-driven):** собственно «что из staged уже отработало → убрать» — за пользователем, завязано на завершение raw-валидации (18 augments не применены, task 017).

### 3. Linter clean on all files

`ruff check src/ tests/ scripts/` должно быть полностью зелёным. Сейчас несколько остаточных pre-existing errors (PLC0415 локальные импорты, PLR0915 длинные функции, PLR1714 `pat != X and pat != Y`, N812 `date as Date`, E501 длинная строка, B905 zip без strict=, и др.) — частично игнорятся в CI, частично just unfixed. Пройти по всем, либо чинить, либо явно добавлять `# noqa: CODE — reason` с обоснованием. Цель: `ruff check src/ tests/ scripts/` exit-code 0 без `--ignore`.

`mypy src/` тоже должен быть зелёным. Сейчас `dividends/tbank.py:116` имеет pre-existing `Argument 1 to "float" has incompatible type "Any | None"`.

### 4. Расширить regression-якоря: LKOH + SBER (не только VSMO)

Сейчас единственный **externally-verified** якорь — VSMO=4.6458% (r(12-1) на 2022-03), потому что автор опубликовал в `info.txt` полный worked example (12 month-end цен + помесячные доходности). Для LKOH/SBER такого внешнего примера **нет** — info.txt их не считает.

Поэтому LKOH/SBER — **snapshot/golden** якоря: зафиксировать self-computed `r(12-1)` на выбранной as-of-date из committed raw, заморозить в тесте ± tol. Ловят дрейф нашего кода (refactor сломал price-adjust → monthly → signal), НЕ внешнюю корректность.

Почему именно эти два: ликвидные, полная история, разные code paths — SBER без сплитов, LKOH с buyback'ами. Оба уже косвенно в author Q1-Q4 snapshot (`test_author_quantiles`: SBER∈Q1, LKOH∈Q4), но как set-membership, не числом.

Реализация: расширить `tests/test_momentum_examples.py` golden-значениями для LKOH и SBER. Значения вычислить один раз из текущего committed состояния и захардкодить.

Upgrade (опц.): если появятся внешние авторские/сторонние значения — заменить snapshot на externally-verified.

После создания — обновить `CLAUDE.md` (строка про info.txt regression-якорь) и `tasks/SPEC.md` (§regression), чтобы упоминали все три якоря и различали verified vs snapshot.

## Acceptance per item

- Каждый пункт = отдельный commit (или серия), отдельный pytest sub-run.
- Никаких изменений в data semantics (только code hygiene + observability).
- Regression-якоря зелёные: VSMO=4.6458% (verified) + LKOH/SBER (snapshot).
