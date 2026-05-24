# Task 006 — Legacy prices backfill (2010-2026)

**Status (2026-05-14)**: ✅ всё закрыто (ingest fix, mfd drop, pipeline re-run,
backtest 2010-2026, methodology, cleanup, forensic walk, mass-drift warning).
Готово к `mv` в `tasks/completed/`.

## What got fixed

Изначально считалось, что ISS не отдаёт pre-2014 историю для голубых фишек, и
mfd.ru закрывает дыру. Фактически ISS отдаёт всё — но
`src/momentum/ingest/prices.py` останавливался на первом непустом board'е (TQBR)
и не запрашивал legacy борды (EQBR/EQNE/EQNL/EQBS/SMAL/…), где лежит pre-TQBR
история.

Фикс в `src/momentum/ingest/prices.py`:
1. `_fetch_segment` — теперь юнионит данные со **всех применимых бордов**
   (фильтр по `[history_from..history_till]` пересечению с окном сегмента),
   priority-dedup (primary wins на overlap, drift 0.05-0.3% между бордами не
   raise — норма для разных сессий).
2. `_board_in_segment_window` — для **predecessor segments** (segment.secid !=
   current ticker) фильтр window отключён: предшественник торговался на тех же
   бордах в более раннее окно.

Тесты: `tests/test_prices.py` — 17 проходят, добавлены 3 новых.

## ISS coverage: before / after

```
SECID    OLD rows  OLD first  | NEW rows  NEW first  diff
SBER         3297 2013-03-25  |    4782  2007-04-02  +1485
GAZP         2994 2014-06-09  |    5085  2006-01-23  +2091
LKOH         3297 2013-03-25  |    6063  2002-02-12  +2766
GMKN         2990 2014-06-09  |    6129  2001-10-31  +3139
ROSN         2994 2014-06-09  |    4963  2006-07-19  +1969
KTSBP        1569 2005-09-15  |    3324  2005-09-15  +1755
ARMD         1125 2007-08-27  |    2049  2007-08-27  +924
VTBR         3372 2007-05-28  |    4180  2007-05-28  +808
RTKM         3788 2001-01-24  |    4289  2001-01-24  +501
TATN         5665 2002-01-04  |    6088  2002-01-04  +423
```

**Aggregate across all 1029 tickers: 866,888 → 1,219,070 строк (+352,182, +40%)**.

## Universe size after liquidity filter (median 12-mo value ≥ 100M RUB)

```
yyyy-mm   OLD univ  NEW univ
2010-12         31        73
2011-12          4        45
2012-06          2        45
2012-12          0        41
2013-06          0        39
2013-12          0        42
2014-06         14        43
2014-12         28        53
2015-06         56        56  ← merge point
```

До фикса backtest **отсутствовал в 2012-2013** (0 тикеров). После — 40-70/месяц,
~10 на квартиль (статистически осмысленно).

## mfd: вердикт — drop

Когда ISS стал отдавать pre-2014 split-adjusted историю, mfd-vs-ISS drift report
теперь меряет **split-adjustment delta** (ISS adjusted, mfd raw), не «недостающие
данные». Top drift кейсы: VTGK, TGKE, MRKV, DVEC, MRKU — все pre-split истории
unadjusted в mfd vs adjusted в ISS. Это **архитектурное расхождение**, не bug.

Решение: **mfd убран из production pipeline** (load_merged_prices удалён). Если
оставить, `load_merged_prices` будет вставлять unadjusted mfd-only дни между
adjusted ISS-днями → искусственные split-shaped разрывы. mfd оставлен как
архив + форензическая утилита для поиска **отсутствующих** splits в
`tickers_manual.json`.

## Changes shipped

### Production code drops

- `src/momentum/config.py` — MFD_* константы удалены
- `src/momentum/io/prices.py` — оставлен только `enumerate_tickers`;
  `load_merged_prices` / `check_drift` / `PriceDriftError` удалены
- `src/momentum/compute/pipeline.py` — `prices_mfd_dir` параметр удалён;
  prices читаются напрямую через `read_jsonl(prices_iss_dir / f"{t}.jsonl")`
- `src/momentum/corporate/detect.py` — то же
- `src/momentum/cli.py` — `--prices-mfd-dir` опции в `compute monthly` и
  `corporate detect` удалены; auto-attach mfd в `ingest prices` тоже
- `tests/test_pipeline_incremental.py` — `prices_mfd_dir: None` убран из fixture
- `data/.gitignore` — mfd-патэрны убраны

### mfd machinery — archived to `mfd_backfill/`

```
mfd_backfill/
├── README.md                          ← committed (как пользоваться, drift forensics workflow)
├── scripts/                           ← committed (5 step + _lib.py с vendored MFD constants и check_drift)
├── research/                          ← committed (5 md: mfd_rate_limits, mfd_tickerless, external_isin_sources, nsd_isin_registry, price_sources_research_mfd_alt)
├── data/
│   ├── .gitignore                     ← * + 3 exceptions
│   ├── mfd_ticker_ids.json            ← committed: 890 {SECID: mfd_id}
│   ├── moex_isin_map.json             ← committed: 2192 SECID→ISIN
│   ├── drift_report.md                ← committed: forensic snapshot
│   ├── mfd_unique_ids.json            ← ignored: 1900 mfd ints
│   ├── mfd_resolve_log.json           ← ignored
│   ├── mfd_id_failed.json             ← ignored: {}
│   └── prices_mfd/ × 874              ← ignored
└── cache/                             ← ignored entirely (~365 MB raw HTTP)
    ├── raw/ × 3800                    ← csv + html для 1900 mfd_id
    └── snapshots/ × 147               ← step1 date probes
```

Скрипты обновлены: пути дефолтят в `mfd_backfill/data/` и `mfd_backfill/cache/`;
импортируют constants и `check_drift` из `mfd_backfill/scripts/_lib.py` (vendored
out of `momentum.config` / `momentum.io.prices`).

### Tests + lint

```
pytest: 250 passed (включая 2 новых теста на mass-drift warning)
ruff: 0 errors in touched files (10 pre-existing: 9 в dividends_fill.py
      + 1 в test_pipeline_incremental.py test_records_to_jsonl_bytes)
```

## What's on disk (актуально)

```
data/prices_iss/              ← 1029 файлов, 1.22M строк (142 MB), production
                              backup data/prices_iss_pre_boardfix/ удалён 2026-05-14
                              после bit-exact containment-проверки (zero loss)

mfd_backfill/data/            ← см. структуру выше
mfd_backfill/cache/           ← см. структуру выше
.iss_cache/                   ← ISS HTTP-кэш для idempotent re-pulls (~281 MB)
```

## Done (re-run + sanity)

1. ✅ **Pipeline re-run** `momentum compute monthly --from-scratch`:
   - 1025 тикеров записано, 401 reblessed (ровно те, кто получил расширение).
   - VSMO anchor 4.6458% intact (`test_momentum_examples.py` 2/2 PASSED).
   - Full pytest: 250/250 PASSED.
   - Blue-chip first months: SBER 2007-04, LKOH 2002-02, GMKN 2001-10, GAZP 2006-01,
     ROSN 2006-07 — сходится с ingest табличкой выше.
   - Raw monthly coverage 2012-12: 329 тикеров (до фикса = 0 после liquidity filter).

2. ✅ **Backtest 2010-2026** `momentum compute backtest --signal curve_fit --start 2010-01`:
   - 197 months, 196 rebalances (2010-01 .. 2026-04).
   - Universe 2010-2013: 38-73 тикеров/мес → 9-18 на квартиль (vs 0 раньше).
   - Cumulative @ 2026-04: Q1 ×13.46, Q4 ×0.73, MCFTRR ×4.35. Q1 > MCFTRR > Q4 —
     каноническая momentum premium иерархия.
   - 2010-2013 sub-period: Q1 ×1.45, Q4 ×0.77, MCFTRR ×1.23 (+68pp spread).

3. ✅ **Holdings sanity 2011-2013**: правдоподобные имена. 2011-06 Q1=AFKS/GAZP/GMKN
   (blue-chip сырьевой пик), 2012-12 Q1=MGNT/DIXY/LKOH/ROSN (retail+oil top),
   Q4 2013 повторяет MTLR/MAGN/MSNG (металлургия+генерация лузеры). Никаких
   галлюцинаторных тикеров.

4. ✅ **Methodology update** `docs/methodology.md`:
   - Универс: добавлена секция про union of boards (TQBR + EQBR/EQNE/EQNL/EQBS/SMAL).
   - Новая секция "Покрытие исторических данных" — окна 2001-2009 / 2010-2013 / 2014+
     с описанием universe size в pre-2014 окне.
   - Disclaimer про mfd как archive-only.

## Done (closing items)

5. ✅ **Cleanup**: `data/prices_iss_pre_boardfix/` удалён 2026-05-14
   (bit-exact containment проверен — zero loss).

6. ✅ **Forensic walk (2026-05-14)**: drift_report регенерирован под post-fix ISS
   (583 тикера). Top-20 по drift-days проанализирован.

   **Результат: zero missing splits.** Yearly median mfd/ISS ratio для всех
   top-20 = 1.000-1.050 (никаких clean step-changes 2x/10x). Top по max-drift
   (MRKU 100%, DVEC 84.74%, VTGK 63.88%) — cherry-pick одиночных дней; при
   этом yearly median у тех же тикеров близок к единице.

   Распределение drift по top-20:
   - **VTGK, MRKHP, RSTIP, IUES**: known wrong-mappings (см. memory
     `project_mfd_tickerless_keep`). Drift = mismatch инструмента, не сплит.
   - **Энергетика 2010-2013** (TGK*/MRK*/FEES/RAO/MSRS/DVEC/SIBN/...):
     board-quote difference между ISS и mfd на post-RAO-UES реорганизации.
     Drift days вышли за 0.5% threshold но величина < 5% годового median —
     это board-noise, а не split.
   - **KMAZ**: yearly median=1.000 во все годы; 456 drift days = pure
     daily-tick noise.

   **Вывод**: пост-фикса ISS не имеет hidden splits, которые надо было бы
   добавить в `tickers_manual.json` / `data/splits/`. Не действуем.

7. ✅ **Mass-drift warning** (2026-05-14):
   - `config.MASS_DRIFT_THRESHOLD = 10`.
   - `compute_all`: при первом превышении threshold во время loop'а — `LOG.warning`
     "mass-drift detected: …+ tickers drifted; consider --from-scratch".
   - Финальное исключение разделено: <threshold = strict per-ticker error
     (потенциально missed split — manual inspect); ≥threshold = mass-rebuild
     wording с прямым suggested fix.
   - Tests: `test_compute_all_mass_drift_uses_softer_error`,
     `test_compute_all_single_drift_keeps_strict_error` (10/10 passing
     в `test_pipeline_incremental.py`).

## Что НЕ входит (deferred)

- Universe extension: 1059 SECID в `mfd_backfill/data/moex_isin_map.json`
  отсутствуют в `tickers.json` — это ETFs (`exchange_ppif`) и GDRs
  (`depositary_receipt`), не common shares. Отдельная задача (если понадобится).
- Перенос `src/momentum/ingest/dividends_fill.py` в архив (task 014).
- Расширение раньше 2000 (mfd сам не отдаёт; ISS — отдельные predecessor SECIDs
  с пустыми сегментами).

## Pinned memory

- `project_mfd_tickerless_keep` — 3-ключ матчинг для mfd, не фильтровать
- `project_pipeline_cadence` — one-shot historical → scripts/; monthly delta → src/cli
- `reference_isin_secid_sources` — fallback порядок для ISIN-резолва
- `feedback_agent_research_verify` — spot-check агентские выводы
- `feedback_network_failures` — но user explicitly allowed retry on ConnectError
  для ISS bulk re-ingest в рамках этой задачи (исключение, не правило)
