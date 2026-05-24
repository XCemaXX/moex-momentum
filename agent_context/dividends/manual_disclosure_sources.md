# Dividend manual-disclosure source matrix

Compiled from task 016 web-research across 48 tickers / 204 augments. Use as starting point when cascade (ISS → dohod → yahoo → tbank) is exhausted and manual disclosure pull is needed.

## Source usage stats (task 016, 204 augments)

| Source | Augments | Best for |
|---|---:|---|
| smart-lab.ru/q/{TICKER}/dividend/ | 77 | Post-2014 RUB-payers, post-2017 USD-payers RUB-equivalent. Per-payment tables with ex-div, registry, period, RUB amount. |
| dohod.ru/ik/analytics/dividend/{ticker} | 50 | Pre-2014 historical, micro-amounts (TGKA, MRKV), some post-redomicile (T from TCSG) |
| ru.investing.com | 20 | Delisted RUB-payers (BEGY/MMBM/TAER/VSMZ pre-2014). **Caveat: page may report USD-denominated values despite RUB label** — verify currency before using |
| mcclinics.com/investors/dividends/ | 12 | MDMG full IR table 2012-2022 — canonical for GDR-issuer RUB-per-share |
| a2-finance.com/en/issuers/{slug}/dividends | 10 | DSKY pre-IPO multi-row AGM splits; secondary cross-check. Shows USD per GDR for Cyprus issuers |
| investfunds.ru | 9 | DGBZP (via ISIN RU0007661682), MFGSP, MSSB pre-2014 |
| vsdelke.ru/dividendy/{slug}.html | 3 | RSTI common (2016 row); supplemental |
| Globaltrans IR (eqs-news.com / globaltrans.com) | 3 | GLTR — primary source confirms RUB-declaration with CBR FX |
| finam.ru, kommersant.ru | 1-2 each | Single-shot confirms via news archives |

## Source-class matrix

| Ticker class | Try first | Fallback | Notes |
|---|---|---|---|
| USD-paying Cyprus/Jersey GDR (POLY, QIWI, GLTR, RAGR, OKEY, ETLN, MDMG, GEMC) | smart-lab → dohod | a2-finance, IR | Look for `руб` / `RUB equivalent` column. Pre-2017 USD-payer RUB-equivalents often unrecoverable (only USD declared) |
| Modern RUB-payer (post-2014) | smart-lab → dohod | finam, vsdelke | Smart-lab has per-payment rows with exact ex-div/registry |
| Pre-2014 historical RUB | dohod → investfunds | investing.com (verify currency!) | Smart-lab and most aggregators don't cover pre-2014 |
| Delisted micro-cap RUB | investfunds (by ISIN) | investing.com, kommersant | Need ISIN if ticker not searchable by symbol |
| Post-redomicile (T/HEAD/X5/FIXR) | dohod for predecessor (TCSG, etc.) | Smart-lab | Treat pre-redomicile period as separate ticker per pipeline policy |

## Pitfalls observed

- **a2-finance**: USD-denominated only for Cyprus-HQ issuers despite English `dividends` page. Don't use as primary for RUB.
- **investing.com BEGY page**: silently switches to USD-denominated values without label. Confirmed RUB via CBR-rate back-calculation (×27-29 RUB/USD for 2010-2011) — only acceptable when other RUB sources are 404.
- **smart-lab RSTI table**: lists both common and preferred in one table; RSTIP-dedicated URL 404s.
- **smart-lab gross vs dohod net**: smart-lab amounts are gross; dohod sometimes post-tax (15% withholding). GEMC 73.52 (smart-lab) vs 72.22 (dohod) = 1.8% tax diff. Pipeline `corporate/apply.py` applies tax constant centrally → store gross.
- **dohod RTKMP table**: muddled fiscal-year vs registry-date columns; cross-check with smart-lab.
- **CAPTCHA**: smart-lab and DuckDuckGo throttle after ~10 queries from same agent. Cache fetches, batch tickers per agent (see `feedback_cache_before_validate.md`).
- **e-disclosure.ru**: requires auth (403) for most company pages — usable only for AGM file archives via direct file URL.
- **MOEX ISS dividends.json post-delisting**: returns empty array (RSTI/RSTIP after 2022-12-30 FEES merger, IRGZ after 2021-12-20, KBTK after 2021-06-21). Cleanup invariant — pull pre-delisting data from disclosure sources directly.

## Brief-prep checklist for future research waves

1. Programmatically dump per-cell data from `validate_with_raw/csv_gap_cells.json` — **never hand-type values into briefs** (see `feedback_agent_research_verify.md` dispatcher-self-error addendum).
2. Per agent: ≤5 tickers, ≤20 cells. Beyond that the agent loses focus.
3. Brief must demand: ≥1 fetched URL per record + exact quoted text. Refuse "synthesis from training memory" verdicts.
4. Acknowledge fallback path explicit: if 2+ sources fail, mark as acknowledge with `tried_urls` list — don't guess.
5. Output to `validate_with_raw/wave{N}_agent{M}.json` with `{ticker, cell_ym, action, registry_close, amount, evidence_url, evidence_quote}` schema for aggregator compatibility.
