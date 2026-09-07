# Reference: recompute + build + review

Runs for **every** scope, after all ingest/reconciliation is done. A price or
dividend change is invisible until these run. Do this once, at the end — a second
recompute mid-run is wasted work.

## Recompute (runbook step 5)

```bash
momentum corporate detect                       # WARN-only anomaly detector
momentum compute monthly --from-scratch         # rebless baselines after ingest
momentum compute backtest --signal curve_fit
momentum compute backtest --signal simple
momentum compute sweep
momentum compute fan
momentum site build

# Re-bless the regression reference — the new month makes pytest red on purpose.
cp data/momentum/curve_fit/q_values.csv tests/reference/q_values_curve_fit.csv
cp data/momentum/simple/q_values.csv    tests/reference/q_values_simple.csv
```

`--from-scratch` is required after an ingest — it re-blesses the baseline hashes the
incremental path guards against. Without it, drifted months trip the baseline gate.

## Checks

- `compute monthly` last line: ticker count and a sample ticker `last=<new-month>`.
- **Triage the split candidates.** `momentum corporate detect` labels every flag with a
  `reason`; only **`sustained_rebase`** is a split candidate, and that queue is normally
  empty. The other classes are diagnostics, not a to-do list — `board_change` points at
  the price source (`task 037`), `near_dividend` at the dividend anchor (`task 036`),
  `limit_move` is an illiquid name on its daily limit. The report itself is gitignored:
  it regenerates byte-identical from the committed data, so there is no diff to read and
  never was — the old "append-only" note here was wrong.
  For each `sustained_rebase`, read the price window around the date. A gap at the open
  with no intraday path, holding at the new level afterwards, is an unadjusted split —
  add it to `data/splits/<T>.csv` (`before,after` = `1,N` for a 1:N split, dated the
  first day at the new price) and rerun with `--from-scratch`. A wide intraday range with
  a volume spike is a genuine move — write it to `data/splits/_acked.json` with the
  reason, which also clears it from the queue next run. Check `data/indices/MCFTRR.csv`
  first: a market-wide V-shape explains a whole cluster of high-beta names at once
  (2026-07: a −9.5% three-day slide then a +4.8% rebound flagged four names, all real).
- `compute backtest` last rebalance: `month=<new-month>`.
- `site build`: `N artefacts → docs/pages`. One aggregated `missing total_return
  treated as 0` line per run is expected: a held ticker whose data ends contributes
  0% and drops out — the author's anti-survivorship convention, not a defect. It is
  not free (per-quartile cost measured in `task 027`), but nothing about it is
  actionable during a monthly run. Same for `mages: no price panel for … dropped`.
- New month present in the site: `rg -o '"20[0-9]{2}-[0-9]{2}"' docs/pages/data.json
  | tail -2` shows the new month-end.
- **`git diff tests/reference/` must be exactly one added row per signal.** More than
  that means the recompute moved history — a dividend backfill or a split fix reaching
  back — and the commit message has to say which. Fewer means the re-bless was skipped
  and `pytest` is still red.

## Review + hand off

1. Serve the site (skill `/serve-site`, or `cd docs/pages && python3 -m http.server
   8000`) and confirm the new month lands on the Q1–Q4 dynamics + alpha charts, the
   Q1 top15 line, `q1_minus_mcftrr` (both alpha charts), `q_history`, `compare`, and
   the mages page.
2. Report what changed: new month-end, dividend adds/skips, cascade outcome,
   detector suspicion count.
3. Suggest a one-line commit message — **the user commits.** Typical split:
   - `chore: monthly data update through <YYYY-MM-DD>`
   - a separate `feat:`/`fix:` if any script/README/skill was touched this run.

Gitignored, so absent from `git status`: `data/momentum/**`, the built site under
`docs/pages/`, and the generated detector reports (`data/splits/_suspicious.json`,
`data/dividends/_gaps.json`). The visible data changes are the ingest deltas — prices,
dividends, indices, manifest — plus any decision overlay you touched (`_acked.json`,
`_conflicts_resolved.json`) and the re-blessed `tests/reference/q_values_*.csv`.
