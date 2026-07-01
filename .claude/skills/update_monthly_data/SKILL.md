---
name: update_monthly_data
description: >-
  Use this skill to bring the MOEX momentum project's data current for a new
  month and regenerate everything downstream. This is the recurring end-of-month
  refresh: market data (prices, dividends, indices like MCFTRR) has fallen behind
  the calendar, so re-pull the latest month(s) from ISS, reconcile lagging
  dividends, recompute the backtest, and rebuild the site. Trigger on any request
  to update, refresh, re-download, or "catch up" the data for the new month —
  Russian or English, whether phrased as a routine ("monthly update", "обнови
  данные", "monthly refresh"), a complaint that data or site is stale ("we're
  into July, site still shows May", "MCFTRR и цены устарели"), or the concrete
  steps ("перекачай котировки и дивы и пересчитай бэктест", "pull the latest
  month and rebuild the pages"). Scope may be prices only, dividends only, or
  both (default). Do NOT trigger for one-off manual edits (a single dividend or
  formula fix), serving the site locally, writing PR descriptions, or explaining
  methodology.
---

# Monthly data update

Bring the pipeline forward one month, then recompute and rebuild the site.
Idempotent by design — reruns add only deltas.

## Scope (read `args`)

| Scope arg | What runs |
|---|---|
| `prices` | price/index ingest → recompute + build |
| `dividends` / `divs` | dividend reconciliation → recompute + build |
| *(empty)* / `all` | both, then recompute + build |

`recompute + build` runs in **every** scope — a price or dividend change is
invisible until the backtest and site are regenerated. This is why the pieces
live in one skill: the tail is shared.

## How to run

1. Do **Phase 0** (preconditions) always.
2. If scope ∈ {`all`, `prices`}: follow `references/ingest_prices.md`.
3. If scope ∈ {`all`, `dividends`}: follow `references/reconcile_dividends.md`.
4. Always finish with `references/recompute_and_build.md` (recompute + site + review).

Read a reference file only when its phase runs — each is self-contained with the
exact commands and the traps specific to that data type.

## Golden rules (apply throughout)

- **Network failures escalate immediately.** No retry loops — a pip/uv/curl/httpx
  timeout goes straight to the user. Sole exception: a *transient* ISS `502`/`5xx`
  mid-batch (e.g. `tickers refresh` dying on one secid) — surface it and offer a
  **single** re-run, not a loop.
- **User stages and commits manually.** Read-only git only. At the end, suggest a
  one-line message (`feat:`/`fix:`/`chore:`), no body, no Co-Authored-By.
- **Never `rm` data before a rerun.** Ingests augment existing files and carry
  manual seed/curation; deleting loses it.
- **Pause for review** at each ⏸ checkpoint in the references. Do not auto-continue.
- All tooling is in the project `.venv` — `source .venv/bin/activate` first.
- Code is English-only; this constraint also holds for anything you write into
  `src/` or `tests/` while fixing a snag mid-run.

## Phase 0 — Preconditions

1. `source .venv/bin/activate`; confirm the `momentum` CLI resolves.
2. Note the last stored month — `tail -3 data/indices/MCFTRR.csv`. Today minus that
   is the month(s) to add. State it to the user so the target is explicit.
3. `git status` — flag any unrelated staged changes before mutating data.

Committed inputs are `data/prices_iss/`, `data/dividends/`, `data/indices/`,
`data/splits/`, `data/manifest.json`, `data/tickers.json`. `data/momentum/**` is
gitignored and regenerated — never hand-edit it.

## Notes

- Skills in `.claude/skills/` are local-dev tooling, not part of the production
  runtime. This one orchestrates existing CLI commands and `scripts/`; it invents
  no new data path.
- The canonical runbook is `README.md §Monthly update` and
  `README.md §Dividend reconciliation`. If this skill and the README disagree, the
  README wins — and fix the skill to match.
