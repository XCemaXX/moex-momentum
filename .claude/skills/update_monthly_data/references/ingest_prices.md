# Reference: price / index ingest (ISS delta)

Runs for scope `prices` and `all`. Pulls the new month of quotes, splits, and the
benchmark from MOEX ISS. All delta — never a full re-pull.

## Commands (in order)

```bash
momentum tickers refresh --force-refresh   # bypass the no-TTL cache. Without it a
                                           # stale snapshot gives false board
                                           # windows → false delisted_after →
                                           # price ingest silently stalls.
momentum ingest prices                     # delta from each ticker's last stored
                                           # date (forward floor). Does NOT re-pull
                                           # history — reassure the user if asked.
momentum ingest splits                     # ISS splits + bonus issues (+ manual)
momentum ingest indices                    # MCFTRR by default
```

## Checks

- `momentum ingest prices` logging shows `from=<new-month-start>&till=...` per
  ticker — confirm it is a delta window, not `from=2012-...` (a full re-pull means
  a ticker lost its stored floor; investigate that ticker, don't let it silently
  re-download years).
- After the run, the tail of any actively-traded ticker's CSV and of
  `data/indices/MCFTRR.csv` should end at the new month-end.
- `ingest prices` prints a detector suspicion count (`data/splits/_suspicious.json`).
  It is WARN-only here; the real detector pass is in `recompute_and_build.md`.

## Traps

- **Transient ISS `502`.** `tickers refresh` is not resilient to a single bad
  gateway mid-batch — it aborts with a traceback on one secid. This is a MOEX-side
  blip, not a bad request. Surface it and offer a single re-run (per the skill's
  golden rules); do not loop.
- `--since` on prices/indices is a **forward floor only** — it can skip ahead but
  never backfills a range already stored. To re-pull a suspect older range, delete
  those rows from the CSV first, then ingest.
