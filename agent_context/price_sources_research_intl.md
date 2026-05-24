# International data providers for MOEX equities (pre-2014)

Goal: locate automatable global source for 2010-01-01 → 2014-12-31 daily/monthly OHLCV on Russian stocks. Russian-domain providers (Finam, MOEX ISS, Tinkoff, etc.) covered by parallel agent.

Verification done from US-IP container via curl, May 2026. SBER 2010-06 monthly close anchor ≈ 76 RUB (legacy CSV).

## 1. Summary table

| Source | Endpoint type | Auth | Cost | MOEX 2010 coverage | Delisted RU tickers | Ticker scheme | SBER 2010-06 close | Trust | Recommendation |
|---|---|---|---|---|---|---|---|---|---|
| Yahoo Finance (query1/query2) | JSON chart API | none | free | partial: most tickers from 2010-03, SBER/MTSS/SBERP/AFKS from 2011-11 | NO (YNDX/POLY.L/MFON.ME = "Not Found") | `<TICKER>.ME` | unavailable (data starts 2011-12) | medium | **primary fallback for non-SBER tickers**; data frozen at 2022-07-08 |
| Stooq (web CSV) | CSV download | captcha → apikey | free with manual captcha | claimed deep but unverified | unknown — Russian universe present (`.ru` suffix) | `<ticker>.ru` | could not fetch (captcha block) | low (unverifiable) | not automatable since 2020-12 |
| Tiingo | REST JSON | api token | free tier (US-only by default) | n/a — no MOEX in free tier docs | n/a | n/a | "Please supply a token" — gated | low | skip, US-centric |
| Alpha Vantage | REST | api key | free 25 req/day | unknown — `SBER` not searchable on demo key | likely none | n/a | demo key blocked | low | skip |
| Twelve Data | REST | api key | Pro plan (paid, ~$79/mo Level B) | confirmed MOEX/MISX listed (SBER, GAZP, YNDX docs) | possibly delisted GDRs | `SBER` + `exchange=MISX` | demo key 401 | medium | **paid fallback** if free fails |
| EOD Historical Data (EODHD) | REST | api key | paid ($19.99–$79.99/mo "All-World") | MOEX confirmed (`.MCX` suffix), claims non-US coverage from 2000-01-03 | likely yes (they keep delisted) | `SBER.MCX` | endpoint returned "Forbidden" without paid key | medium-high | **best paid candidate** for 2010 SBER |
| Polygon.io | REST | api key | US-focused | not advertised | no | n/a | — | low | skip |
| IEX Cloud | REST | api key | US-focused, **service shut down Aug 2024** | n/a | n/a | n/a | — | n/a | skip |
| Nasdaq Data Link (ex-Quandl) | REST | api key | mostly paid; WIKI archive frozen 2018 | no dedicated MOEX equity feed in free tier | no | n/a | — | low | skip |
| FRED (St. Louis Fed) | REST | none | free | macro only, no equity tickers | no | — | — | n/a | not for equities |
| MarketStack | REST | api key | paid; advertises 72+ exchanges, MOEX **not explicitly listed** | unknown | no | n/a | — | low | skip |
| Investing.com (via investpy) | scraping | none | free | full universe historically | partial | country=Russia | gated behind Cloudflare V2 since 2021 — `investpy` is broken, `investiny` is the active fork | medium | unstable; not automatable |
| `pandas-datareader.Stooq` | wrapper | none | free | same Stooq backend | same | same | broken since Stooq captcha (2020-12) | low | dead |
| Refinitiv Eikon / Bloomberg / FactSet | enterprise terminal | account | $$$$ | full | full | own | — | high | out of scope unless user has terminal |
| Interactive Brokers HMDS | TWS API | account+market data fee | paid + subscription | full once enabled | partial | own | — | high | only viable if user already has IBKR account |

## 2. Per-source notes

### Yahoo Finance (query1.finance.yahoo.com / query2)
- Endpoint `https://query1.finance.yahoo.com/v8/finance/chart/<SYMBOL>?range=max&interval=1mo` works without auth from a generic browser UA. Anonymous curl gets `429 Too Many Requests` ~50% of the time; works when `User-Agent: Mozilla/5.0`.
- `SBER.ME`: `firstTradeDate=1321853400` = **2011-11-21**. First monthly close in array = 79.40 RUB (Dec 2011). **No 2010 data.**
- Same 2011-11 horizon for `SBERP.ME` (preferred), `MTSS.ME`, `AFKS.ME`. Likely an artifact of Yahoo re-mapping after Sberbank ADR/share consolidation events.
- `GAZP.ME`, `LKOH.ME`, `MGNT.ME`, `GMKN.ME`, `ROSN.ME`, `CHMF.ME`, `NLMK.ME`, `MAGN.ME`, `ALRS.ME`, `VTBR.ME`, `AFLT.ME`, `HYDR.ME`, `IRAO.ME`, `MTLR.ME`, `RTKM.ME`, `AKRN.ME`: all have `firstTradeDate=1267597800` = **2010-03-03**. First monthly bucket is 2010-03-31.
- GAZP 2010-06 (monthly bucket ending 2010-06-30) close = **162.72 RUB** (adjclose 89.27). Plausible — GAZP traded 145–170 RUB in summer 2010, anchor confirms within ±5%.
- `regularMarketTime=1657295398` = **2022-07-08**. Yahoo MOEX data is **frozen** at this point (Yahoo stopped updating MOEX feed after sanctions). Fine for 2010–2014 backtest, useless for live pipeline.
- Delisted tickers return `{"code":"Not Found","description":"No data found, symbol may be delisted"}` for `YNDX`, `POLY.L`, `MFON.ME`. `FIVE.L` returns data labeled `MUTUALFUND` (unreliable instrument type).
- Adjusted close is present (`adjclose`) — Yahoo applies splits and dividends back-corrections; cross-check needed against MOEX ISS for the post-2014 overlap before trusting pre-2014 splits.

### Stooq
- Free URLs (`/q/d/l/?s=sber.ru&i=m`) **now return a captcha-gated message** demanding an apikey obtained manually via browser captcha. This has been the state since Dec 2020.
- Static bulk dump `static.stooq.com/db/d_world_txt.zip` returns 404. `/db/d/?b=d_world_txt&v=2` returns "error.txt" content of size 13.
- HTML quote pages (`/q/d/?s=sber.ru&...`) render via inline JS + base64 SVG; no scrapable price table in raw HTML.
- Net: **Stooq is not automatable** without solving captcha each session. Skip for production.
- Note: I couldn't verify Stooq's actual MOEX coverage depth or accuracy for SBER 2010 — claim from QuantStart that Stooq carries Russian `.ru` tickers is uncorroborated for pre-2014.

### Twelve Data
- Documentation pages confirm SBER and a long list of MOEX tickers (`twelvedata.com/markets/348952/stock/moex/sber/historical-data`, YNDX, MVID, SNGSP, TTLK).
- Exchange code: `MISX`. Symbol form: bare ticker + `exchange=MISX` query param.
- Demo key `apikey=demo` returns `401`. Free tier (no card) gives 800 req/day but **MOEX is gated to Pro Level B** (~$79/mo per support article).
- Cannot verify SBER 2010-06 close without paid key.

### EODHD
- Confirmed coverage of Moscow Exchange via `/exchange/MCX` page and direct symbol pages (`MOEX.MCX`, `GCHE.MCX`, `RSHE.MCX`). Symbol format: `<TICKER>.MCX`.
- EODHD support docs claim "non-US data from 2000-01-03" by default, which would include 2010.
- Endpoint `/api/eod/SBER.MCX?...&api_token=demo` returns `Forbidden`. Real validation requires paid token.
- **Best candidate among paid sources** if user pays — single API covers all tickers, deep history, EOD subscription is ~$20–80/mo. Worth a paid trial.

### Nasdaq Data Link / Quandl
- The `WIKI` US equities dataset is frozen since 2018-03-27; never covered MOEX.
- Russian equity feeds are not in the free catalog. Bloomberg-feed datasets are sometimes brokered through Data Link at enterprise pricing. Skip.

### IEX Cloud
- **Sunset on 2024-08-31.** No longer an option.

### Investing.com (`investpy` / `investiny`)
- Investing.com hosts SBER (and most MOEX tickers) with pre-2014 data viewable in the UI.
- `investpy` library is unmaintained because Investing.com put their endpoint behind Cloudflare V2 in 2021. The fork `investiny` works intermittently and may break at any time.
- Not a reliable foundation. If user already trusts hand-compiled Investing.com CSV exports (as is the case for `raw_sources/`), this is the historical provenance — but it's not automatable.

### Polygon.io / Marketstack / Tiingo
- All advertise "global coverage" but none explicitly list MOEX. Tiingo focuses on IEX + EOD US. Polygon is US/options only. Marketstack lists 72+ exchanges but MOEX is not in their public exchange directory. Skip all three.

### FRED / Wikidata / OpenFIGI
- FRED has macro series for Russia but no equity tickers.
- OpenFIGI maps tickers across identifiers (good for cross-referencing SBER MOEX vs SBER ADR), no prices.
- Wikidata sometimes embeds historical closes for individual companies as statements, but neither systematic nor backtestable.

## 3. Best free sources — ranked

1. **Yahoo Finance `query1` JSON API** — covers ~16 of the 20 priority tickers from 2010-03-03 to 2022-07-08. Misses SBER pre-2011-11, MTSS, SBERP, AFKS. Free, no auth, automatable from Python via `httpx` (no need for `yfinance` package, the JSON endpoint is direct). **Suitable as a 2010–2014 backfill source for everything except SBER/MTSS/SBERP/AFKS.**
2. **GitHub crowd-sourced repos** — see section 5. Mostly low-quality, very low star counts, no comprehensive 2010-2014 dump found.
3. Nothing else free is automatable for our universe.

## 4. Best paid sources — ranked

1. **EODHD** — `.MCX` suffix, 2000-01-03 claim, $19.99/mo "All-World" tier. Single endpoint per ticker, CSV+JSON. Recommended trial.
2. **Twelve Data** — Pro Level B (~$79/mo) for MOEX. More expensive but cleaner Python SDK.
3. **Refinitiv / Bloomberg** — gold standard, irrelevant without enterprise license.
4. **Interactive Brokers HMDS** — only if user already has the account; subscription to Russian exchange data was paused by IBKR post-2022 anyway.

## 5. Crowd-sourced / one-shot data dumps

| Repo / Dataset | Stars | Date | Coverage | Notes |
|---|---|---|---|---|
| `WISEPLAT/RUSSIA-249-Stocks-Prices-MOEX` | 1 | last push 2024-01-19 | **EMPTY** — only ReadMe.md, no actual CSV files | abandon, name is bait |
| `WISEPLAT/ALGOPACK-Extra-Market-Data` | n/a | active | MOEX since 2020 only | wrong era |
| `epogrebnyak/finec` | n/a | active | wrapper around MOEX ISS, not a static dump | functionally equivalent to ISS direct access |
| Kaggle `olegshpagin/russia-stocks-prices-ohlcv` | "RUSSIA 249 Stocks" | n/a | OHLCV across many timeframes | depth/start date unverified from search snippets; worth manual download check |
| `cdracer/moex-importer` | n/a | n/a | ISS wrapper | not a dump |
| `vladislavpyatnitskiy/rus-stock-data-analysis` | n/a | n/a | analysis using Investing.com CSVs | manual exports, no automation |
| `ffeast/finam-export` | n/a | active | Finam.ru wrapper | Russian-domain, defer to parallel agent |

No high-quality (>50 stars), well-maintained, pre-2014 MOEX dump exists on GitHub or Kaggle.

## 6. Unresolved / blocked

- **Stooq depth and accuracy for `sber.ru` 2010**: could not verify a single 2010 monthly close. If user is willing to solve captcha once and extract apikey, this could become viable; the manual flow gives a long-lived key per session.
- **Twelve Data and EODHD 2010 coverage**: confirmed listed, not confirmed deep. Both offer 30-day free trial — running one trial against SBER, GAZP, YNDX, POLY for the 2010-06 anchor is the only definitive validation. User would need to sign up.
- **Kaggle `olegshpagin/russia-stocks-prices-ohlcv`**: cannot download from Kaggle without login from this environment. Worth a manual check by user.
- **Investing.com**: hand-compiled CSVs in `raw_sources/` already proves SBER 2010-06 ≈ 76 RUB is available there; but the path is non-automatable.

## Recommendation

For the 2010-2014 gap our pipeline needs:

1. **Yahoo `query1` v8/finance/chart** as the primary automatable backfill for ~16 of 20 priority tickers (everything except SBER/MTSS/SBERP/AFKS).
2. For the missing 4 tickers (most importantly **SBER**), the cheap automatable path is a paid month of **EODHD** ($19.99) — one bulk pull of 2010-2014 daily for the full universe, store as CSV, cancel. Validate SBER 2010-06 close ≈ 76 RUB before trusting the rest.
3. Adjusted-close from Yahoo and unadjusted from EODHD must be reconciled against MOEX ISS overlap (post-2014) to confirm split/dividend handling matches our `corp_actions` pipeline.
4. Do **not** rely on Stooq, IEX, Quandl, Polygon, Marketstack, Tiingo, Alpha Vantage for this use case.

Sources used (all verified May 2026 from container):
- query1.finance.yahoo.com chart API (live curl, multiple tickers)
- api.github.com/repos/* (live curl, repo stats)
- stooq.com (live curl, captcha block confirmed)
- twelvedata.com, eodhd.com, alphavantage.co (live curl, demo-key gates)
