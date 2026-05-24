# mfd.ru backfill — archived

**Status**: superseded by the ISS board-union fix (see `task 006`). The production pipeline
no longer depends on mfd data. The folder remains as (a) a historical archive
of work done and (b) a forensic utility for finding missing splits.

## What's inside

```
mfd_backfill/
├── scripts/           ← step1..step4, working code (committed)
├── research/          ← results of research agents on mfd/ISIN sources
├── data/
│   ├── mfd_ticker_ids.json   ← committed: 890 resolved {SECID: mfd_id}
│   ├── moex_isin_map.json    ← committed: 2192 SECID→ISIN (including delisted)
│   ├── drift_report.md       ← committed: snapshot mfd vs ISS drift
│   ├── prices_mfd/           ← gitignored: 874 jsonl, parsed mfd OHLCV
│   ├── mfd_unique_ids.json   ← gitignored: 1900 mfd internal IDs (step1)
│   ├── mfd_resolve_log.json  ← gitignored: per-SECID match audit
│   └── mfd_id_failed.json    ← gitignored: empty {} from step2
└── cache/             ← gitignored entirely (expensive to rebuild)
    ├── raw/           ← 1900 csv + 1900 html (current step2 version)
    └── snapshots/     ← 147 html (date probes from step1)
```

## Why keep the data

Re-pulling takes ~1.5 hours (3800 HTTP requests to mfd.ru, throttle 1 rps).
The `cache/raw/` cache is ~475 MB — kept locally, not pushed to the repo.

`mfd_ticker_ids.json` and `moex_isin_map.json` are committed — these are **results of manual
resolution**, easier to track in git than to regenerate (step3 requires online
requests to ISS + manual collision-tiebreak edits).

## Pipeline (if ever needed for re-run)

```bash
# step 1: walk the calendar, find all mfd_id for 2010-2026
python mfd_backfill/scripts/step1_index_dates.py

# step 2: bulk download 1900 mfd_id × (csv + html) → cache/raw/
# Throttle 1 rps, 0 retries (per memory `feedback_network_failures`)
python mfd_backfill/scripts/step2_bulk_download.py

# step 3a: pull paginated ISS securities → data/moex_isin_map.json (487→2192)
python mfd_backfill/scripts/step3a_extend_isin_map.py

# step 3: offline resolve mfd_id → SECID by 3-key (Код → ISIN → name)
python mfd_backfill/scripts/step3_resolve.py

# step 4: parse cached csv → data/prices_mfd/{SECID}.jsonl
python mfd_backfill/scripts/step4_load.py

# step 4 + drift report (requires fresh data/prices_iss/ at root):
python mfd_backfill/scripts/step4_load.py --drift-report
```

## Drift forensics: "map of missing splits"

After we fixed the ISS ingest (full board union), `drift_report.md`
shows not data holes but a **systemic split-adjustment delta**: ISS returns
adjusted prices, mfd returns raw unadjusted. So drift > 1-2% on a ticker = either
a missing split in `data/tickers_manual.json`, or `iss/statistics/splits`.

**Workflow for finding missing splits**:

1. Re-run `step4_load.py --drift-report` after changes in `tickers_manual.json` /
   `data/splits/`.
2. In `drift_report.md` sort by `max abs drift` desc.
3. **Filter**: consider only splits after 2010-01-01 (mfd itself does not return
   earlier; the backtest starts 2010+, splits before that are of no interest to us).
4. For tickers with `max abs drift > 5%`:
   - Open its mfd csv: `mfd_backfill/cache/raw/{mfd_id}.csv`
   - Find the date where the mfd/iss ratio changes sharply → this is the split date
   - Compare with `iss/statistics/engines/stock/markets/shares/securities/{SECID}/splits.json`
   - If the split is not on ISS — add it to `data/tickers_manual.json` with `type=split`
5. Re-run `step4_load.py --drift-report` — the drift should collapse.

**Known wrong-mappings** (exclude from the forensics workflow): `VTGK`, `IUES`, `MRKH`.
VTGK has a strange 1.1-ratio cluster, causes unknown; IUES is an IRAO-era
mismatch (pre-2015-01 consolidation); MRKH — too few overlap days (7) for
conclusions.

## What **not** to do

- **Do not use** `mfd_backfill/data/prices_mfd/` as a price source for the
  pipeline/backtest. ISS now covers everything mfd covered, plus
  split-adjusted (see `task 006`).
- **Do not delete** `cache/raw/` without special need — `step2_bulk_download.py`
  is idempotent (cache hits skip), but a full re-fetch is 1.5 hours at 1 rps.
- **Do not commit** `cache/`, `prices_mfd/`, `mfd_resolve_log.json` —
  `data/.gitignore` enforces this.

## References

- `task 006` — task status and the ingest-fix decision
- `agent_context/iss_isin_delisted_research.md` — general research on ISS endpoints
  for delisted tickers (not mfd-specific, stays in the main `agent_context/`)
