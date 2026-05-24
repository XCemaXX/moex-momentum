# Drop in-progress current month from compute output

`to_monthly_close` (`src/momentum/compute/monthly.py:24`) сейчас группирует daily-prices по `to_period("M")` и берёт `tail(1)`. Если сегодня 2026-05-08, оно создаёт строку 2026-05 с `month_end_date=2026-05-08` и `close_adj` от 8 мая — пайплайн дальше трактует этот mid-month close как «end-of-May», публикует фантомный NAV и broken r(12-1) для следующего месяца.

Конвенция методологии (см. `docs/methodology.md` секция «Конвенция периода»): период M существует **только после завершения месяца календарно**. Пока сегодня внутри M — последняя строка остаётся за M−1.

## Fix

В `to_monthly_close` добавить параметр `as_of: pd.Timestamp | None = None` (default = `pd.Timestamp.utcnow().normalize()`). После построения `traded` отбросить trailing-период, если `as_of <= traded.index[-1].end_time`. Чисто-функционально, тесты могут подавать фиксированную дату.

Эквивалентное правило: период M считается completed iff `as_of > M.end_time` (последний день M, 23:59:59 UTC).

## Tests

`tests/test_monthly.py`:
- `test_to_monthly_close_drops_in_progress_period` — daily prices с трейлингом в текущем месяце, `as_of` внутри этого месяца → последняя строка отсутствует.
- `test_to_monthly_close_keeps_completed_current_month` — `as_of` на первый день следующего месяца → текущий месяц присутствует (его last trading day и есть month-end).
- Существующие VSMO/SBER тесты остаются зелёными (исторические данные, все периоды completed).

## Regeneration

После фикса:
1. `momentum compute monthly --all` — пересборка `data/computed/monthly/*.jsonl` без 2026-05 строк.
2. `momentum compute backtest --signal curve_fit` — `q_values.jsonl` без фантомного 2026-05, `holdings/2026-05.json` удаляется.
3. То же для `--signal simple` (используется для cross-check, см. `task 009`).
4. `momentum site build` — `q_history.html` без майской строки.
5. Удалить `data/computed/{curve_fit,simple}/holdings/2026-05.json` если регенерация их не перезаписывает.

## Acceptance

1. `data/computed/curve_fit/q_values.jsonl` заканчивается 2026-04 (или последним завершённым месяцем на момент прогона).
2. `data/computed/curve_fit/holdings/` не содержит файлов за in-progress месяц.
3. `tests/test_momentum_examples.py` (VSMO 4.6458%) — зелёный без изменений.
4. `tests/test_author_quantiles.py` — зелёный, Jaccard на 2026-03 не меняется (исторические данные не тронуты).
5. `agent_context/legacy_prices_diff.md`, `legacy_dividends_diff.md`, `author_quantiles_diff.md` — бит-в-бит идентичны до фикса (фикс трогает только trailing-период текущего месяца, исторические значения не сдвигаются).
6. На сайте q_history последняя строка = последний завершённый месяц. Заголовок/подпись страницы явно говорит «состав Q1-Q4 по итогам месяца» — поправить если сейчас формулировка двусмысленная.

## Side check

При прогоне ровно на последний торговый день месяца (например 2026-04-30 в течение дня) — `as_of` ещё внутри апреля, апрель будет отброшен. Это корректно: пока день не закрылся клирингом, close не финализирован. Период появится назавтра, 2026-05-01. **Подтвердить ожидаемое поведение** в тесте `test_to_monthly_close_excludes_current_trading_day`.

## Не входит

- Изменение semantics period-labelling (по итогам M vs держание в M) — уже зафиксировано в методологии, не трогаем.
- Отдельная Live-секция на сайте (решено: не нужна, последняя строка и есть live signal).
- Replication-режим, где пайплайн запускается «как если бы сегодня было 2026-04-15» для воспроизведения исторических снимков — отдельная задача если понадобится.

## Зависимости

Независимо от 005/006/008/009. Чистый bugfix + doc consistency.
