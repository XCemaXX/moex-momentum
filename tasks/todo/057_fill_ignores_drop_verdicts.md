# fill-dividends не учитывает drop-вердикты

> Создана 2026-10-01 во время месячного обновления.

## Проблема

`fill_dividends` (`src/ingest/dividends/fill.py`) читает из `_conflicts_resolved.json`
только записи `ignore`, и только чтобы заглушить **конфликты**. Если в CSV нет строки
на эту дату, запись источника проходит в `new` и пишется.

`drop` fill не читает вовсе. Отменённый дивиденд, который агрегатор держит в таблице,
возвращается каждым настоящим (не dry-run) прогоном fill. Удаляет его только
следующий `apply-conflicts`.

Так SVETP 2026-06-01 0.1716 (smart-lab) и попал в данные. ГОСА 26.06.2026 не
состоялось, дивиденда не было. Строку удалили 2026-10-01 через `drop`. Проверка
после этого:

```
momentum ingest fill-dividends -t SVET -t SVETP --dry-run
SVET:  new=1 by_source={'skill_fill_smartlab': 1}
SVETP: new=1 by_source={'skill_fill_smartlab': 1}
```

Сейчас данные чистые только потому, что в README шаг 4 (`apply-conflicts`) идёт
после шага 3 (fill). Защита держится на порядке команд.

## Что сделать

В `fill_dividends` отбрасывать предложенные записи, совпадающие с `drop`-вердиктом
по (ticker, registry_close, match.amount, match.source), до `reconcile`. Считать их в
`FillResult` отдельным счётчиком (`n_dropped_by_verdict`), чтобы было видно в выводе.

Заодно решить, должен ли `ignore` с `registry_close` глушить и `new`, а не только
конфликты. Сейчас скил прямо говорит: «для фантома только drop», потому что ignore
не помогает.

## Готово, когда

- `fill-dividends -t SVET -t SVETP --dry-run` даёт `new=0`.
- Есть тест: drop-вердикт глушит запись, которой нет в CSV.
- Правило «never ignore a phantom» в `reconcile_dividends.md` упрощено или
  оставлено, по итогам решения про `ignore`.
