# MOEX Momentum Pipeline

Pipeline for Russian equities: ingest from MOEX → compute Q1–Q4 momentum → interactive charts on GitHub Pages.

## Source of truth

- **Requirements** — `tasks/SPEC.md`.
- **Architectural decisions and phase 1-12 history** — `task 000` (closed). Inside it, the "Design decisions (locked)" section holds the choices agreed with the user (universe, formula, stack, storage format). **Do not revisit without an explicit request.** Some entries were later superseded by their own tasks and carry an "Отменено" note naming it — the note wins over the decision above it. New active tasks live in `tasks/todo/NNN_*.md`.
- **Data-source research** — `agent_context/data_sources.md` (ISS endpoints with confirmed examples).
- **Open tasks** — `tasks/todo/NNN_*.md`. **Reference them only via `task NNN`, never by path.** Tasks migrate between `todo/` and `completed/`; the ID never changes. Closing a task = `mv` into `tasks/completed/`.

## Layout

- `src/` — production code, flat: `config.py` plus `ingest/`, `adjustments/`, `momentum/`, `mages/`, `storage/`, `viz/`, `cli/`. There is no umbrella `src/momentum/` package.
- `agent_context/` — internal research documents and generated reports (legacy diff, etc.).
- `docs/` — GitHub Pages output (`docs/pages/*.html`) plus the Markdown the site renders: `methodology.md`, `mages_intro.md`, `mages_methodology.md`. Those three are build inputs, not artifacts.

## Working in the project

- Before any implementation, reread the relevant phase of task 000 in full.
- The domain is Russian, but **all Python code is English-only**: names, comments, docstrings, `typer.Option(help=...)`, `typer.echo(...)`, log formats, `raise ValueError("...")`. Russian remains only in `data/` (canonical/aliases), `tasks/`, `raw_sources/`, and `SPEC.md`.
- `raw_sources/` — read-only input: `info.txt` holds the externally-verified regression anchor VSMO=4.6458% (the author's worked example). Plus LKOH/SBER snapshot anchors (self-computed, frozen in `tests/test_momentum_examples.py` — they catch code drift, not external correctness). The CSVs were recovered from broken encoding (do not re-encode them again).
- Constants (taxes, fees, formula coefficients, detector thresholds) — single `src/config.py`. Do not scatter them across modules.
- The stack is closed: Python 3.12, uv, httpx, pandas, plotly, jinja2, typer, pytest, ruff, mypy. No kaleido, no Makefile. Do not propose alternatives.
- **Unavailable sources** (closed Telegram channels such as `t.me/kpd_investments`, anti-bot pages, auth-walls) — **do not fabricate content**. Tell the user the resource is unavailable and ask them to send the export — they confirmed they are willing to do so.
