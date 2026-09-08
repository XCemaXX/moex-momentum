# scripts/

One-shot and operational tooling, run by hand. Nothing here is imported by `src/`, exercised by tests, or run in CI.

Two-cadence rule (locked): one-shot historical/backfill work lives here;
recurring work lives in `src/` behind the `momentum` CLI. Do not mix the two —
anything CI or the monthly runbook needs is a CLI command, not a script here.

| Path | Category | When to run |
|---|---|---|
| `setup.sh` | operational | Bootstrapping the local environment (uv / venv). |
| `build_plotly_bundle/` | operational | Re-vendoring `plotly.min.js` for the offline Pages site. Only when the bundle needs a new trace type — the SHA is pinned in tests. |
| `backfill/` | mixed | `fetch_tbank_dividends.py --refresh` then `cascade_merge_dividends.py` are step 3 of the monthly dividend runbook — recurring, and so far the one exception to the rule above. `fetch_yahoo_dividends.py` is done: Yahoo dropped Russian names in 2022 and its cache is a frozen snapshot. |
| `parse_reference_quartiles.py` | done | Parsed the author's Q1–Q4 lists out of the Telegram blog export into `agent_context/`. Re-run only on a fresh export. |
| `compare_reference_quartiles.py` | research | Ad-hoc: our quartiles against the author's reference. |
| `compare_formulas.py` | research | Ad-hoc: `simple` vs `curve_fit` statistics off the on-disk backtest outputs. |
| `q017_ref_membership_nav.py` | research | Ad-hoc: the `task 017` membership-swap experiment. |

The weight sweep and the concentration fan used to live here. They are recurring —
CI rebuilds them on every push — so they moved to `momentum compute sweep` and
`momentum compute fan`.
