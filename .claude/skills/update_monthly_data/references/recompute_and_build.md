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
- **Triage the new detector flags** — WARN-only does not mean skip-it. The file is
  append-only, so `git diff data/splits/_suspicious.json` is exactly this month's
  additions. For each, read the price window around the date: `open` equal to the
  previous `close` plus a wide intraday range plus a volume spike = a genuine move,
  leave it. A gap at the open with no intraday path = an unadjusted split — add it to
  `data/splits/<T>.csv` and redo the recompute. Check `data/indices/MCFTRR.csv`
  first: a market-wide V-shape explains a whole cluster of high-beta names at once
  (2026-07: a −9.5% three-day slide then a +4.8% rebound flagged four names, all
  real). `data/splits/_acked.json` can silence a reviewed flag, but it is empty by
  convention — do not start acking selectively.
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
