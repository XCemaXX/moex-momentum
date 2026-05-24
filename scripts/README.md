# scripts/

One-shot and operational tooling, run by hand. **Not** part of the recurring pipeline: nothing here is imported by `src/`, exercised by tests, or run in CI.

Two-cadence rule (locked): one-shot historical/backfill work lives here;
recurring monthly delta pulls live in `src/ingest/` behind the `momentum` CLI.
Do not mix the two.

`build_plotly_bundle/` - Vendor `plotly.min.js` for the offline GitHub Pages site (no CDN).
`setup.sh` -Bootstrap the local environment (uv / venv).

`backfill/` - artefact of a completed one-time dividend backfill: `fetch_yahoo`/`fetch_tbank`
populated `.fill_cache/`, `cascade_merge` folded the result into `data/dividends/`. The work
is done; the scripts still run (cache-only) if a re-fill is ever needed.
