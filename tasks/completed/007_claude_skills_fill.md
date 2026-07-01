# Claude skills для интерактивного заполнения пропусков

## РЕЗОЛЮЦИЯ (DONE, 2026-07-01) — superseded

Исходный план (два интерактивных per-gap скилла `/fill-dividends` и `/fill-splits`,
оборачивающих `dividends_fill.py`, append в JSONL) **устарел и вытеснен другим
дизайном**:

- **Формат/пути изменились** (task 014, storage-рефактор): JSONL → CSV,
  `src/momentum/ingest/dividends_fill.py` → `src/ingest/dividends/fill.py` (flat).
  Оригинальная спецификация ниже опирается на снятые допущения.
- **Дивидендный gap-filling закрыт другим путём**, отработанным на практике:
  batch-CLI `momentum ingest fill-dividends` (dohod) + `cascade_merge_dividends.py`
  (yahoo/tbank, windowed, future-guarded) + ручной `augment` в
  `_conflicts_resolved.json` → `apply-conflicts`. Аппрув-на-запись сохранён (dry-run
  + чекпоинты), но через CLI, не через отдельный интерактивный скилл.
- **`/fill-splits` не понадобился** — сплиты покрыты ISS (`ingest splits`) +
  `tickers_manual.json`; детектор (`corporate detect`) остаётся WARN-only сигналом.
- Операционная обвязка теперь живёт в скилле **`update_monthly_data`**
  (`.claude/skills/update_monthly_data/`, scope prices/dividends/all) и в
  `README.md §Dividend reconciliation`.

Дальнейших действий не требует. История ниже — как есть, для контекста.

---

Бывший Phase 13 из `task 000` — два skill'а для interactive-режима. Делается **после task 005**, потому что 005 строит batch-ядро (`src/momentum/ingest/dividends_fill.py`), которое skill `/fill-dividends` тонко оборачивает в UX-обвязку.

## Цель

Два skill для интерактивного заполнения дыр — пользователь дёргает slash-команду, агент идёт в источники, показывает proposed-records, ждёт аппрува, append'ит в JSONL.

## `.claude/skills/fill_dividends/SKILL.md`

```
Trigger: пользователь дёргает /fill-dividends.
Процесс:
1. Читает data/dividends/_gaps.json (генерация — см. ниже, в phase 6 добавить).
2. Для каждой дыры (ticker, period): идёт в источники по приоритету (см. agent_context/data_sources.md):
   а) dohod.ru — fallback #1 (даёт declared_date в дополнение к amount).
   б) smart-lab.ru/q/{TICKER}/dividend/ — fallback #2 (sanity cross-check).
   в) e-disclosure.ru — fallback #3 (через WebFetch, curl 403).
3. Парсит таблицу, формирует proposed-record в формате data/dividends/{TICKER}.jsonl.
4. Показывает diff пользователю, ждёт аппрува.
5. После аппрува — append к JSONL, удаляет запись из _gaps.json, source = "skill_fill_<source_name>".
```

**Pre-flight check** (наследие task 005): перед источниками — проверка на редомициль. Если `is_redomicile_target(ticker)` истинно — отказываемся бэкфилить с пояснением «predecessor dividends not bridged — см. methodology.md». Не делаем тихий no-op.

**Donor для парсера dohod.ru**: [poptimizer_old/src/web/dividends/dohod_ru.py](https://github.com/WLM1ke/poptimizer_old/blob/master/src/web/dividends/dohod_ru.py) — `pandas.read_html(...)[2]`. Smoke-test обязателен — HTML за 8 лет мог поплыть.

**`_gaps.json` генерация** — добавить в phase 6 ingest:
- Список `(ticker, year)` пар, где у тикера есть котировки за год, но за этот год нет ни одной записи о дивидендах в JSONL — флаг для проверки. Эвристика, не truth (тикер мог не платить дивы тот год).

## `.claude/skills/fill_splits/SKILL.md`

Симметрично — читает отчёт detector'а (phase 7) `data/splits/_suspicious.json`. Большинство сплитов уже подтянуто из ISS `/iss/statistics/.../splits.json` (phase 7), поэтому skill включается только для:

- Bonus issues (BELU 2024-08-20-class) — но они уже в `tickers_manual.json`, detector не должен их выдавать.
- Pre-2018 случаи (если detector что-то нашёл).
- Реальные расхождения детектора с ISS-данными.

Источники: smart-lab `smart-lab.ru/q/{TICKER}/`, e-disclosure через WebFetch, manual-input.

## Risks

- Skills не имеют гарантии корректности — это AI-инструмент. Аппрув обязателен на каждую запись.
- Skills в `.claude/skills/` **НЕ попадают в production-runtime**; они только для локальной разработки. Не часть pipeline. Документировать в README.

## Verification

- На искусственно созданной дыре (удалить SBER 2020-07 div из JSONL) skill `/fill-dividends` восстанавливает данные с правильным source-полем.
- На очищенном `data/splits/SBER.jsonl` skill `/fill-splits` находит исторические сплиты SBER (если такие были).
- Pre-flight redomicile gate: на X5 skill отказывается работать и логирует объяснение.

## Зависимости

- **Task 005 завершена** — `dividends_fill.py` существует, skill оборачивает его в interactive-UX.
- `_gaps.json` сгенерирован в phase 6 ingest (если ещё нет — добавить тут же).

## Не входит

- Сами dohod/smart-lab парсеры — они в task 005 (batch-ядро).
- Бэкфилл редомицильных предшественников (out of scope by methodology policy).
