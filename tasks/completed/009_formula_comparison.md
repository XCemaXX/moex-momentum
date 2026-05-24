# Formula comparison — `simple` vs `curve_fit` со статистикой

В `agent_context/backtest_findings.md` (Phase 9) сравнение headline: Q1 NAV у `simple` (10.81) выше, чем у `curve_fit` (10.46), но `curve_fit` даёт монотонный порядок Q1>Q2>Q3>Q4. Выбор `curve_fit` по умолчанию обоснован монотонностью как robustness-критерием — но **без явной статистической проверки**: нет p-value на разницу Q1, нет Sharpe/DD/turnover сравнения, нет measure of monotonicity.

Задача — полный compare как gate-документ. После него либо `curve_fit` подтверждается осознанно, либо `simple` становится default.

## Метрики (все на полной панели 2012-12 → последний доступный месяц)

Per signal, per quartile (Q1, Q2, Q3, Q4) и для long-short Q1−Q4:

- **CAGR** (annualized).
- **Sharpe** (annualized, монтхли log-returns, rf=0).
- **Max drawdown** (на NAV-кривой).
- **Calmar** (CAGR / |MaxDD|).
- **Annual turnover** — сумма абсолютных весовых изменений / 2 / лет.
- **Hit rate** — доля месяцев с Q1 > MCFTRR.

И отдельно:

- **Spearman ρ** между порядковым номером квартиля и средней доходностью квартиля (по всем месяцам). 1.0 = идеальная монотонность.
- **Bootstrap CI** на разнице Q1-NAV между формулами: ресэмплинг по месяцам (block bootstrap, длина блока 12 мес) → 95% CI на `NAV_simple / NAV_curve_fit − 1`. Если 1.0 в CI — разница не значима.
- **t-test / Wilcoxon** на месячных Q1-returns simple vs curve_fit (paired). p-value.

## Артефакт

`agent_context/formula_comparison.md` — таблицы, NAV-чарт обоих Q1 на одном Plotly, статистический раздел.

**Статистику на сайт не выносим** — этот research-док остаётся внутренним. Дефолтные страницы и default `--signal` остаются `curve_fit`. Исключение: explorer-страница `task 20` показывает `q1_simple` рядом с `q1_curve_fit` как тоглящиеся линии (визуальное сравнение, не статистика), делается одновременно с этой задачей.

## Implementation

- One-shot скрипт `scripts/compare_formulas.py` (не часть production CLI — research only).
- Читает `data/momentum/{simple,curve_fit}/q_values.csv` (`simple` сейчас stale `.jsonl` — пересчитать) + holdings.
- Считает все метрики и bootstrap inline через `numpy`/`pandas`. Без новых depend'ов.

## Acceptance

1. Все метрики посчитаны для обеих формул, разница Q1-NAV получает явный 95% CI и p-value.
2. Spearman ρ по квартилям подтверждает / опровергает «curve_fit монотонный, simple — нет» количественно (не на глаз).
3. Отдельный bullet-вывод: **«default остаётся curve_fit потому что …»** или **«меняем default на simple потому что …»**. Решение строится из метрик, не из интуиции.
4. Если решение — сменить default на `simple`, синхронно:
   - `src/cli/momentum_cmd.py:49` + `src/cli/site_cmd.py:14` — default `--signal` меняется.
   - `docs/methodology.md` — переписать секцию «Сигнал» под `simple`, `curve_fit` упоминается как experimental.
   - Пересборка сайта.
   - Phase 12 re-verification: Jaccard к автору на 2026-03 (`agent_context/author_quantiles_diff.md` перегенерировать) — пороги Q1/Q4 ≥ 0.5 сохраняются. **Если падают → задачу не закрываем, разбираемся: либо comparison criteria неполны, либо автор использует curve_fit-like формулу и наш simple не репликабельный.**

## Не входит

- Сравнение adaptive-lookback вариантов формулы (это `task 008`, со своим compare).
- Walk-forward stability (хочется отдельной задачей: окно 5 лет, sliding step 1 год, как поведение формул меняется во времени).
- Параметрический sweep по весам curve_fit (0.9/0.1 vs 0.7/0.3 vs 0.5/0.5) — отдельная research-задача.

## Зависимости

Независимо от `task 005/006/008`. `curve_fit` уже на диске (`data/momentum/curve_fit/q_values.csv`); `simple` лежит как stale `.jsonl` — пересчитать перед стартом (`momentum compute backtest --signal simple`).
