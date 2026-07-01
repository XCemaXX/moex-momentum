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
python scripts/compute_weight_sweep.py
python scripts/compute_topn_fan.py
momentum site build
```

`--from-scratch` is required after an ingest — it re-blesses the baseline hashes the
incremental path guards against. Without it, drifted months trip the baseline gate.

## Checks

- `compute monthly` last line: ticker count and a sample ticker `last=<new-month>`.
- `compute backtest` last rebalance: `month=<new-month>`.
- `site build`: `N artefacts → docs/pages`. The `missing total_return … treated
  as 0` lines and any `mages: no price panel for … dropped` warning are
  pre-existing and harmless — do not chase them.
- New month present in the site: `rg -o '"20[0-9]{2}-[0-9]{2}"' docs/pages/data.json
  | tail -2` shows the new month-end.

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

`data/momentum/**` is gitignored, so it will not appear in `git status`; the visible
data changes are the ingest deltas (prices/dividends/indices/manifest) plus
`docs/pages/`.
