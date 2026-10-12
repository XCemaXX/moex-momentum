# MAIL → VKCO: противоречие между ручной записью и ISS changeover

## Проблема

- `data/tickers_manual.json`: `MAIL → VKCO`, `type = redomicile`, `renamed = 2021-10-12`.
  По политике (task 005, 052) это «юрлицо сменилось, длинный разрыв, не сшиваем».
- ISS changeover содержит ребро `MAIL → VKCO` от 2021-12-13. `src/ingest/prices.py` разворачивает
  changeover-рёбра в сегменты, поэтому `data/momentum/monthly/VKCO.csv` начинается с 2020-07 —
  цены расписки MAIL **сшиты** с акцией VKCO.
- `src/ingest/dividends/fill.py` (redomicile cutoff) режет дивиденды VKCO по 2021-10-12.

Две политики для одного эмитента: цены сшиты, дивиденды — нет. Даты тоже расходятся
(2021-10-12 против 2021-12-13).

## Практическое влияние (2026-10-05)

Сейчас нулевое: у VKCO нет файла дивидендов — VK и Mail.ru Group не платили. Проблема в
несогласованности данных: при любой будущей выплате или правке политики она всплывёт.

## Что сделать

1. Проверить по ISS, была ли MAIL расписка (`TYPE = depositary_receipt`) и есть ли торговый разрыв
   между MAIL и VKCO. Короткий разрыв → это обычное changeover-переименование: убрать запись из
   `tickers_manual.json`. Длинный → оставить запись и не сшивать цены.
2. Согласовать дату с ISS.
3. Сверить с подходом task 058: предшественники-расписки идут отдельными тикерами, без сшивки.

## Acceptance

- Для VKCO цены и дивиденды подчиняются одной политике.
- Тест на инвариант: если пара `old → new` есть в `tickers_manual.json` как redomicile, changeover
  не сшивает её цены (или наоборот — по итогам п. 1).

## Результат (2026-10-12)

- ISS: MAIL — `TYPE = depositary_receipt` (ГДР VK Company Limited, ISIN US5603172082). Последний торговый день
  MAIL — 2021-12-13, первый день VKCO — 2021-12-14. Разрыва нет: это changeover-переименование той же GDR.
- 2021-10-12 — дата смены названия Mail.ru Group → VK, не смена юрлица. Запись `MAIL → VKCO` удалена из
  `tickers_manual.json`. Цены и дивиденды VKCO теперь под одной политикой: сшивка через changeover.
- Реальная редомициляция (GDR → акция МКПАО «ВК», ISIN RU000A106YF0) прошла осенью 2023 под тем же SECID VKCO:
  разрыв торгов 2023-09-18 … 2023-10-20. Ряд VKCO через него непрерывен. Разрезать один SECID модель не умеет;
  дивидендов у VK нет, влияния нет.
- MAIL остаётся в словаре как старая нога changeover, как TCSG, EPLN и др. Один слот во вселенной держит
  `_drop_renamed_duplicates`: MAIL до 2021-11, VKCO с 2021-12.
- Тест `test_redomicile_pair_has_no_changeover_edge`: ни одна пара redomicile (old ≠ new) не совпадает с ребром
  changeover. На прежнем `tickers_manual.json` падает на `(MAIL, VKCO)`.
- `test_predecessor_cutoff_manual_wins_even_with_changeover` переведён на синтетическую пару.
- `docs/methodology.md`: MAIL→VKCO перенесён из примеров редомициляций в примеры переименований.
- Пересчёт с нуля: `data/momentum`, `docs/pages/data.json`, страница Магов и эталон `tests/reference` побайтно
  не изменились.
