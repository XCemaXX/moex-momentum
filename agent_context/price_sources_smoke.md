# Historical price sources smoke-test (task 006 research)

Probe ticker: MTSS. Date: 2026-05-12. Goal: find alternative sources for daily/monthly closing prices when MOEX ISS doesn't cover 2010-2013.

## Results

| Source | URL pattern | HTTP | Page content | Usable for task 006? |
|---|---|---|---|---|
| dohod.ru | `/ik/analytics/share/{ticker}` | 200, 4.4 MB | Redirects to `/share` index — **analytical ratings table** (P/E, ROE, DCF potential) for all stocks, 1140 rows. No prices. | ❌ |
| dohod.ru | `/ik/{ticker}` | 404 | — | ❌ |
| smart-lab.ru | `/q/{TICKER}/` | 404 | Does not work for a single ticker | ❌ |
| smart-lab.ru | `/q/{TICKER}/f/y/` | 200, 83 KB | **Annual IFRS reporting** (revenue, profit, EBITDA). No prices, there is an `Изм%` column which in principle allows reconstructing price changes but this is a very murky path | 🟡 only as last resort |
| finam.ru | `/profile/.../export/` | **403** | anti-bot | ❌ |
| finam.ru | `/profile/.../` | **403** | anti-bot | ❌ |
| investfunds.ru | `/stocks/{TICKER}/` | 404 | dead-end | ❌ |
| investing.com | historical-data page | **403** | anti-bot wall | ❌ |
| yahoo finance | `{TICKER}.ME/history` | 302 → consent wall | requires a cookie session | ❌ |
| archive.org wayback | snapshot of ISS endpoint | timeout | wayback does not index ISS-JSON stably | ❌ |

## Verdict

**Found no public alternatives to MOEX ISS for historical prices** pre-2014 without an anti-bot wall or a login requirement.

For task 006 the only realistic path:
1. `raw_sources/Российские_акции_цены.csv` (legacy CSV, monthly closes) — the current task 006 plan already provides for this.
2. Manual export by the user from closed channels or paid services (kpd_investments, some Bloomberg/Refinitiv archives).
3. Reverse-engineering wayback — theoretically possible but labor-intensive.

**Recommendation:** task 006 stays as planned — legacy CSV is the primary source. We stop actively searching for other sources until a concrete request from the user appears.
