# Project structure refactor + storage policy

> Переписана 2026-05-19. Original task была про mfd dividend tier (отвергнут task-012) и prices commit policy (устарел task-006). Live items сохранены: (a) smartlab cleanup, (b) smoke-test для filled-data anchor, (c) commit-policy дискуссия. Плюс integrated требования из user-разделов «ВАЖНАЯ ИНФА».

## Context

Repo сейчас:
- `src/momentum/` flat — всё в одном umbrella package, cli.py 604 LOC, `ingest/dictionary.py` 340 LOC.
- `.gitignore` policy инвертирована относительно нового требования: raw data (prices_iss/, dividends/*.jsonl, indices/, splits/*.jsonl) gitignored как «regenerable из ISS», computed (q_values, holdings/) committed для Pages.
- Format: JSONL, 146 MB working tree из-за повторяющихся ключей.
- 44.5% записей в dividends/ — AI-augmented (skill_fill_dohod/tbank/yahoo/disclosure). Empirical phantom-rate floor 0.9% (13/1412 из task-016 cleanup).

Цель: clone → `uv sync` → `pytest` → `momentum compute backtest` пересчитан offline без сети. Если формула меняется, ничего не fetch-ится. Computed momentum НЕ хранится. Raw caches gitignored. Compact diff-friendly format. AI-augmentation задокументирована с opt-out.

## Decisions (locked)

| Axis | Pick | Notes |
|---|---|---|
| Layout | Flat top-level packages под `src/` | `src/{ingest,adjustments,momentum,viz,io,cli}/`. Без umbrella `src/momentum/`. Project's name «momentum» становится именем доменного subpackage для signal+backtest. |
| Format | CSV with header | -57% size (146M→62.8M); stdlib `csv`; clean diffs; industry-standard (Zipline, Shiller, backtrader, pyfolio). |
| Commit policy | Raw committed, computed gitignored | Repo self-sufficient. Working tree ~75 MB. |
| `mfd_backfill/` (545M legacy) | Оставить gitignored | Уже не в git, занимает только диск. |
| AI opt-out | `--source-trust=strict` | Default `full`; opt-in `strict` (только `moex_iss + manual_disclosure`). README "Data provenance" раздел. |
| CLI verbs | stable | `momentum ingest prices` остаётся. Разрезаем только Python-модули cli.py → cli/. |
| Smoke-test fills | add | `tests/test_fill_anchors.py` — 1 якорь на источник. |
| Ingest cadence | single fetcher, `--since` flag | Не дублировать full vs delta как отдельные пакеты. |

## Target src/ structure

```
src/
├── ingest/
│   ├── prices.py            # ISS daily bars (full + --since=delta)
│   ├── dividends/
│   │   ├── iss.py
│   │   ├── dohod.py
│   │   ├── tbank.py
│   │   ├── yahoo.py
│   │   ├── merge.py
│   │   ├── conflicts.py
│   │   └── fill.py
│   ├── splits.py
│   ├── indices.py
│   └── tickers.py           # split нынешнего dictionary.py (340→3 files)
├── adjustments/             # = бывший corporate/
│   ├── apply.py
│   ├── detect.py
│   └── dividend_gaps.py
├── momentum/                # доменный subpackage: signal + backtest
│   ├── signals.py           # r(12-1), r(6-1), σ(12)
│   ├── universe.py
│   ├── backtest.py
│   └── pipeline.py          # orchestration: raw → monthly → quartiles
├── viz/
│   ├── charts.py
│   └── site.py
├── storage/                  # бывший io/ — `io` конфликтует со stdlib import io
│   ├── records.py            # бывший atomic.py — read/write_records, write_csv_atomic
│   ├── schemas.py            # per-domain FIELDS + CASTS
│   └── tickers_glob.py       # бывший prices.py — enumerate_tickers (был misnamed)
├── cli/
│   ├── __init__.py          # typer app composition
│   ├── ingest_cmd.py
│   ├── momentum_cmd.py
│   ├── adjust_cmd.py
│   ├── site_cmd.py
│   └── tickers_cmd.py
├── config.py
└── logging_setup.py
```

Imports:
- `from ingest.prices import ...`
- `from momentum.signals import r_12_1`
- `from adjustments.apply import adjust_dividend_amounts`
- `from storage.records import read_csv, write_csv_atomic`

`pyproject.toml` перечисляет каждый top-level package явно. CLI entry-point `momentum` резолвится в `cli:app`.

## Target data/ tree

**Committed (source-of-truth):**
```
data/
├── tickers.json, tickers_manual.json, tickers_unavailable.jsonl
├── manifest.json
├── prices_iss/{TICKER}.csv          # 142M JSONL → ~70M CSV
├── dividends/
│   ├── {TICKER}.csv                 # 1.5M JSONL → ~0.7M CSV
│   ├── _acked_no_div.json
│   ├── _conflicts_resolved.json
│   └── _external_blacklist.json
├── indices/{INDEX}.csv
└── splits/
    ├── {TICKER}.csv
    └── _acked.json
```

**Gitignored:**
```
data/momentum/                       # q_values, holdings, monthly (бывший data/computed/)
.fill_cache/                         # all HTTP caches (iss + dohod + tbank + yahoo)
validate_with_raw/
mfd_backfill/
scratch/, raw_sources/, agent_context/
```

## Migration stages

Каждый stage = один user-commit. Tests green между stages. VSMO=4.6458% invariant через все stages.

| # | Commit message | Touched | Risk |
|---|---|---|---|
| 0 | `docs: rewrite task 014 + open task 018 for follow-ups` | 2 task files | LOW |
| 1 | `chore: smartlab removal + consolidate caches under .fill_cache/` — (a) удалить `SmartLabFetcher` из `src/momentum/dividends/`, убрать из cli `--sources` (0 записей в data → no-op для tree); (b) `mv .iss_cache/ .fill_cache/iss/`, обновить cache_dir в `ingest/prices.py` / `ingest/indices.py` / `ingest/dictionary.py` etc., обновить `.gitignore` (убрать `.iss_cache/`). Структура каждого fetcher's cache: `.fill_cache/{iss,dohod,tbank,yahoo}/`. | ~6 src + 2 test + .gitignore | LOW |
| 2 | `feat: csv read/write in io.atomic + dual-format tests` — добавить `read_csv` / `write_csv_atomic`. JSONL functions сохраняются для backward read. `--format=csv` flag в CLI write paths. | ~5 src + 3 test | MED |
| 3 | `chore: convert data tree jsonl→csv + invert gitignore` — `scripts/migrate_to_csv.py`. Все `data/{prices_iss,dividends,indices,splits}/*.jsonl` → `*.csv`. `.gitignore`/`data/.gitignore` инвертируются. Pre/post assert VSMO=4.6458%. | `.gitignore` + ~1100 файлов + 1 script | HIGH (git bloat ~75M) |
| 4a | `refactor: flat top-level layout` — `git mv src/momentum/* src/`, удалить umbrella. Параллельно: `io/` → `storage/` (избежать конфликта со stdlib `import io`), `io/atomic.py` → `storage/records.py`, `io/prices.py` → `storage/tickers_glob.py` (был misnamed — содержит enumerate_tickers), `corporate/` → `adjustments/`, `compute/` → `momentum/` (доменный subpackage), `compute/momentum.py` → `momentum/signals.py`, `dividends/` → `ingest/dividends/`. Обновить imports (~133 sites). `pyproject.toml` packages list + entry point `cli:app`. CLI verbs неизменны. | ~25 src + 14 test + pyproject | HIGH |
| 4b | `refactor: split cli.py + ingest/dictionary.py` — `cli.py` (604 LOC) → `cli/` subpackage (ingest_cmd.py, adjust_cmd.py, momentum_cmd.py, site_cmd.py, tickers_cmd.py, `__init__.py` для typer app composition). `ingest/dictionary.py` (340 LOC) → 3 файла (`iss_listing.py` + `iss_changeover.py` + `ticker_lifecycle.py`). Тесты остаются нетронутыми. | ~2 src + 10 new src | MED |
| ~~5~~ | ~~`--source-trust=strict` opt-out~~ — **дропнут как лишняя сложность**. Pre-existing audit показал phantom rate 0.9%, не критично; default `full` остаётся единственным режимом. Если когда-нибудь понадобится — re-design в task 018. | — | — |
| 6 | `ci: simplify pipeline + smoke-test fills + recompute job` — `.github/workflows/`: новый `recompute` job (`momentum compute backtest` + assert VSMO), `pages` workflow добавляет recompute step (т.к. q_values теперь gitignored). `tests/test_fill_anchors.py` — per-source якоря. | 2 yml + 1 test + README | LOW |
| 7 | `chore: drop transitional jsonl scaffolding` — после стабилизации csv-only: упростить `read_records` (убрать jsonl branch + sibling fallback), убрать `write_records_atomic` (writers использовать `write_csv_atomic` напрямую), удалить dual-ext globs (`enumerate_tickers`, `cli.py:105`, `compute/universe.py:43`, `corporate/dividend_gaps.py`, `tests/test_dividend_invariants.py::_iter_ticker_files`, `dividends/conflicts.py::apply_conflicts_to_universe` fallback). `scripts/migrate_to_csv.py` оставляется в `scripts/` как one-shot historical artifact (per project convention для one-shot scripts). Опционально: drop `read_jsonl`/`write_jsonl_atomic` если ни один caller не остался. | ~10 src + 3 test | MED |

## Verification

После каждого stage:
1. `uv run pytest -q` — все тесты зелёные.
2. `uv run momentum compute backtest && python -c "..."` — VSMO=4.6458% invariant.
3. `git diff --stat HEAD~1` — review.
4. `du -sh .git data/`.
5. После stage 3: fresh-clone worktree → `pytest` + `momentum compute backtest` offline (без сети).
6. После stage 6: `.github/workflows/pages.yml` рендерит `docs/pages/` offline из committed CSV.

## Не входит (entirely out of scope)

- Замена pages workflow на GitLab — repo на GitHub Actions, не путать.
- Q1<Q2 в 2013-2022 methodology audit — task 017, не блокирует этот рефактор.

## Deferred follow-ups → task 018

См. `tasks/todo/018_post_refactor_followups.md`:
1. Fetcher protocol unification (dohod/tbank/yahoo).
2. Cache eviction policy (1GB `.iss_cache/` + `.fill_cache/`).
3. `validate_with_raw/` cleanup.
4. `mfd_backfill/` final decision (delete vs archive).
5. AI-fill audit-trail metadata.
