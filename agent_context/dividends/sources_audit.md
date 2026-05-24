# Dividend source redundancy analysis (task 012 phase 5)

Snapshot after cascade --apply + Phase 4 corrections + source rename
(`skill_fill_smartlab`/`skill_fill_rbc`/`skill_fill_investfunds` → `manual_disclosure`).

Regen: `.venv/bin/python -c '...'` snippet at end. Not part of production pipeline.

## Per-source headline

| Source | Records | Tickers | Pre-2014 | Sole-bucket | Verdict |
|---|---:|---:|---:|---:|---|
| `moex_iss` | 1574 | 210 | 22 | 1526 | KEEP — core, irreplaceable |
| `skill_fill_yahoo` | 776 | 153 | 389 | 733 | KEEP — primary pre-2014 carrier |
| `skill_fill_tbank` | 433 | 78 | 262 | 383 | KEEP — second pre-2014 carrier; complements yahoo (kopeck-rounded but covers RUAL USD-native) |
| `skill_fill_dohod` | 215 | 39 | 77 | 181 | KEEP — only cross-source for ISS 2-decimal-truncation fixes |
| `skill_fill_disclosure` | 14 | 9 | 0 | 11 | KEEP (borderline) — covers ISS-missing major events (X5 redomicile, etc.) |
| `manual_disclosure` | 10 | 5 | 0 | 0 | KEEP — never sole, always supplements (multi-tranche split fills) |
| `skill_fill_smartlab` | — | — | — | — | **ARCHIVED** — moved 4 PHOR records to `manual_disclosure`; removed from `VALID_SOURCES` + `SOURCE_PRIORITY` |
| `manual` | 0 | 0 | 0 | 0 | **ARCHIVED** — dead enum value, never used in any production JSONL. Was redundant with `manual_disclosure`. Test fixtures updated to use `manual_disclosure`. |

**Sole-bucket** = the `(ticker, year-month, currency)` bucket has records from only that single source. `manual_disclosure` always supplements → 0 sole, which is by design (it adds tranches that ISS missed).

## Why nothing else under the < 10 threshold

Initial cut had two synthetic sources from prior-session manual augments:
- `skill_fill_rbc` (2 records — MISB/MISBP)
- `skill_fill_investfunds` (4 records — RTSB/RTSBP)

Both were not in `VALID_SOURCES`. Renamed to `manual_disclosure` (catch-all for human-researched evidence; URL belongs in `_conflicts_resolved.json:reason`). This collapses the source enum back to a stable set.

## Pre-2014 carrier ranking (cumulative)

| Cascade tier | Records ≤ 2013-12-31 | % of all pre-2014 |
|---|---:|---:|
| moex_iss | 22 | 3% |
| + dohod | 99 | 13% |
| + yahoo | 488 | 65% |
| + tbank | 750 | **100%** |
| manual_disclosure / disclosure | 0 | — |

ISS alone covers only 3% of pre-2014. Without yahoo+tbank the pre-2014 backfill collapses. Both must stay.

## Archived: `skill_fill_smartlab`

- 4 PHOR records that pre-dated the cascade architecture (kept for historical regen).
- Renamed to `manual_disclosure` in JSONLs and `_conflicts_resolved.json`.
- Removed from `VALID_SOURCES` + `SOURCE_PRIORITY` in `src/momentum/dividends/types.py`.
- `src/momentum/dividends/smartlab.py` (SmartLabFetcher class) is now unused in production
  but still referenced by `validate_with_raw/compare_dividend_sources.py` (gitignored
  one-shot research script). **Not deleted** — leave for future ad-hoc comparison.

## Regen snippet

```python
from collections import Counter, defaultdict
from pathlib import Path
import json
cnt = Counter()
tk_per_src = defaultdict(set)
pre2014_per_src = Counter()
unique = defaultdict(list)
for p in Path("data/dividends").glob("*.jsonl"):
    if p.name.startswith("_"): continue
    tk = p.stem
    for line in p.open():
        r = json.loads(line)
        src = r.get("source", "?")
        cnt[src] += 1
        tk_per_src[src].add(tk)
        if r["registry_close"] < "2014-01-01":
            pre2014_per_src[src] += 1
        unique[(tk, r["registry_close"][:7], r.get("currency","RUB"))].append(src)
sole = Counter(srcs[0] for srcs in unique.values() if len(set(srcs)) == 1)
```
