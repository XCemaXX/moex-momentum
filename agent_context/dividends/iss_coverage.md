# ISS dividends coverage — state as of 2026-05-10

Raw numbers from a full ingest over the 1029-ticker universe (after `momentum ingest dividends`).

## Coverage

| metric | value |
|---|---|
| tickers in universe | 1029 |
| with ≥1 ISS dividend record | 210 |
| with no records at all | 819 |
| total div records | ≈1100 |
| gaps in `_gaps.json` (year × ticker) | 2870 |

819 tickers with no records ≠ 819 non-payers. Most are preferred-only / new / never-paid. The real non-payers will go into `_acked_no_div.json` via the skill in phase 13.

## Distribution of gaps by year

```
2000:  6   2007: 142   2014: 222   2021: 149
2001:  9   2008:  89   2015: 238   2022: 149
2002: 11   2009:  88   2016: 232   2023: 130
2003: 31   2010:  99   2017: 225   2024: 117
2004: 21   2011:  83   2018: 177   2025: 140
2005: 47   2012:  47   2019: 125
2006:132   2013: 20    2020: 141
```

Peak — **2014-2017** (≈225 gaps/year). This is the pre-sanctions peak of the universe (max number of traded common+preferred), and **this is precisely where ISS coverage is worst**. After 2018 ISS is noticeably better — gaps there are more about real non-payments (sanctions, freeze, GAZP's CAPEX-pause, delistings).

## Ticker-level anchors

- **SBER** — coverage from 2019. Gaps 2013-2018, 2022. Actual payments 2013-2018 are missing in ISS (fill needed).
- **VTBR** — coverage 2016-2025. Gaps 2017-2018 (actual skip by the company) + 2022-2024 (sanctions/consolidation). 2017-2018 are real misses, need confirmation via ext source.
- **GAZP** — coverage up to 2022. Gaps 2023-2025 are real non-payments (sanctions, CAPEX). Candidate for acked.
- **LKOH** — **0 gaps**. Pays regularly, ISS records everything.
- **MTSS** — gaps 2011, 2013-2017. MTSS paid every year — these are pure ISS holes for fill.

## Implications for phase 13

The `/fill-dividends` skill is **not a smoke test**. Volume of work:
- **2870 (year, ticker) pairs** to check.
- Most will go to **ack** (companies that genuinely did not pay in Y) — especially from the 2014-2017 cluster (small-cap, illiquid).
- For **fill** — 100-300 pairs (rough estimate based on the share of "large" names in the gap list).
- At least 2 sources needed: dohod.ru + smart-lab.ru. e-disclosure.ru only via WebFetch (curl 403).
- The skill must be batch-friendly — process 50+ gaps per pass, otherwise the backfill will take months.

`_acked_no_div.json` will be the main output of the skill — fills (new JSONL records) will more likely be the minority.

## What _gaps.json does NOT catch

Current heuristic: `≥6 distinct active months in year Y AND 0 div records in Y`. Misses:
- Mid-year delistings (ticker traded Jan-Jun → flags Y as a gap, although the company simply disappeared). These will be acked via the skill.
- Tickers with **partial** records: Y paid, but the record covers only one of two interim dividends. The heuristic considers Y covered → the gap is not flagged. This is a **silent miss**, fixed only by the phase-12 cross-check (legacy CSV).
