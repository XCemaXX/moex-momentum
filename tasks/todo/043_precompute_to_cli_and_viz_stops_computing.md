# Precompute в CLI; `viz/` перестаёт считать стратегию

> Создана 2026-09-05 по итогам сквозного ревью репозитория (13 линз, агенты). Дорожка A. Объём M. После `task 042`.

## Проблема 1: правило двух каденций нарушено, и документ это отрицает

`scripts/README.md:3` утверждает буквально: «nothing here is imported by `src/`,
exercised by tests, or **run in CI**». А `.github/workflows/pages.yml:40,43` запускает
`scripts/compute_weight_sweep.py` и `scripts/compute_topn_fan.py` **на каждый push в
main**, и без них `compare.html` не рендерится (`src/cli/site_cmd.py:61-69`).

Это не one-shot, а часть регулярной сборки, живущая вне CLI: захардкоженные пути
(`compute_weight_sweep.py:29-32`), `print()` вместо логгера, `assert` как
продакшн-гейт (`compute_topn_fan.py:82` — исчезнет под `python -O`).

## Проблема 2: `viz/` считает стратегию в момент рендера HTML

`src/viz/site_builder.py:205-254` (`_q1top15_nav`) грузит панель месячных доходностей
(`load_panel`), ранжирует по скору (`score_ranking`) и прогоняет полный NAV-цикл
(`nav_from_selections`). Слой визуализации импортирует `momentum.topn_fan`,
`momentum.universe`, `momentum.transitions` и `config.COMMISSION_PER_SIDE`.

Кривая top-15 — самая быстрорастущая линия на главной (NAV 8.30 против 6.00 у Q1) —
нигде не сохраняется и не покрыта регрессией на уровне артефакта. То же делает
`_mages_page_context:323`.

## Что сделать

1. `momentum compute sweep` и `momentum compute fan` как subcommands; пути через
   `typer.Option`; `assert` → явный `raise`/`typer.Exit`. CI и README зовут CLI.
2. Кривую top-15 считать в `momentum compute backtest` и писать рядом с `q_values.csv`;
   `viz` получает готовый ряд через `series_registry`, как sweep и fan.
3. То же для mages: `momentum compute mages` пишет `data/mages/curve.csv`, страница
   только читает.
4. Переписать `scripts/README.md` в таблицу «скрипт | категория | когда запускать» по
   всем восьми позициям — сейчас перечислены три.

## Заодно

- `src/cli/site_cmd.py:81-83` хардкодит `mages_dir`, `indices_dir`, `monthly_dir`, при
  том что остальные шесть путей выведены в `typer.Option`.
- `build_site` — 19 keyword-параметров, из них 12 `Path | None` в паттерне
  «есть файл → путь, нет → None»; вызывающая сторона — 20 строк `x if x.exists() else None`.
  Свести к `@dataclass(frozen=True) SiteInputs` с классметодом `from_dirs(...)`.
- `NAV_LINKS` (`site_builder.py:56`) статичен, а `compare.html` и `mages_index.html`
  рендерятся условно: у клонировавшего в шапке каждой страницы висят ссылки на 404.
  Тест `tests/test_site_builder.py:133` этот дефект **закрепляет**, требуя ссылку на
  каждой странице.

## Инвариант

Сайт визуально не меняется. `q_values.csv`, `q1_nav.csv`, `fan_concentration.csv` —
байт-в-байт.
