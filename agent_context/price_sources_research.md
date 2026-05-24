# Pre-2014 MOEX equity price sources — programmatic access

Date: 2026-05-12. Goal: close the gap **2010-01..2013-12** in `data/prices/{T}.jsonl` (legacy CSV covers monthly close only, without OHLCV and without volumes). MOEX ISS `aggregates.json` confirms the range **2011-11-21 → 2026-05-11** — before that ISS is empty on any board (EQBR/TQBR/etc. checked).

Verification anchor: SBER 2010-06-30 close ≈ 76 RUB (from legacy CSV).

## 1. Summary table

| Source | Access type | Auth | Earliest date | Coverage MOEX equities | Cost | SBER 2010-06-30 close | Trust | Recommendation |
|---|---|---|---|---|---|---|---|---|
| **mfd.ru `/export/handler.ashx`** | HTTPS GET → CSV/TXT | none | 2000s (confirmed 2010-01) | Full MOEX TickerGroup=16, OHLCV+VOL | free | **76.5 RUB** ✅ | **HIGH** — exchange prices 1:1, volumes in shares | **USE — primary** |
| MOEX ISS `/iss/history/...` | HTTPS GET → JSON | none | **2011-11-21** | Full MOEX, OHLCV+VOL+VALUE | free | NA (2010 empty) | high (but gap) | existing primary 2011-11+ |
| MOEX ISS `aggregates.json` | HTTPS GET → JSON | none | 2011-11-21 (same) | Aggregated | free | NA | high | only for cross-check |
| finam.ru `export.finam.ru/table.csv` | HTTPS GET → CSV | **ServicePipe anti-bot** | theoretically 2000s | Full MOEX | free, but cookie challenge | **BLOCKED** | low (was high) | **AVOID** — requires headless solver |
| T-Bank Invest API (Tinkoff) | gRPC/REST | API token (brokerage account needed) | rolling 6 years | Current MOEX universe | free for "Инвестор" tariff | NA for 2010 | medium | **NOT USABLE** for pre-2020 |
| Alor Open API | REST | OAuth + brokerage account | rolling unspecified | MOEX | free | NA | medium | requires account |
| smart-lab.ru `/q/{T}/f/y/` | HTML | none | annual reporting | reverse-engineerable | free | NA (not prices) | low | ❌ |
| dohod.ru | HTML | none | analyst ratings only | n/a | free | NA | low | ❌ |
| investfunds.ru | HTML + `/api/` | unknown | 2002+ judging by the chart | unknown | unknown | not extracted | medium | fallback, requires reverse-engineering |
| conomy.ru | HTML | none | unknown | analytical | free | not tested | low | ❌ |
| Yahoo Finance / investing.com | HTML | consent wall + cookie | rolling | full | free with login | n/a | low | ❌ |
| Cbonds / rusbonds.ru | n/a | paid | unknown | bond-focused | paid | n/a | n/a | irrelevant for equities |
| Refinitiv RIC | proprietary | $$$ enterprise | full | full | paid | n/a | high | irrelevant without subscription |

## 2. Detailed per-source notes

### mfd.ru — the only working free API

**URL pattern (verified):**
```
https://mfd.ru/export/handler.ashx/{filename}?TickerGroup={market_id}
  &Tickers={security_id}&Period={timeframe}&StartDate=DD.MM.YYYY
  &EndDate=DD.MM.YYYY&RecordFormat=0&FieldSeparator=%3B
  &DecimalSeparator=.&DateFormat=yyyyMMdd&AddHeader=true&Fill=false
```

Parameters confirmed from `mfd.ru/export/` (JS handler `Mfd.goTo`, line 183):
- `TickerGroup=16` → MosBirzha Shares and Funds. **Ignored** by the handler (it filters TickerGroup out of params), but we pass it as valid for UI consistency.
- `Tickers={id}` — internal mfd ID. SBER=1463, GAZP, LKOH etc. We obtain the IDs via `/marketdata/search/?ticker_search={SECID}` (HTML parsing).
- `Period`: 0=tick, 1=1min, ..., 7=daily, 8=weekly, 9=monthly.
- `RecordFormat`: 0=full OHLCV+OPENINT, 1=HLCV, 2=CV, 3=OHLC+amount+volume.

**SBER daily 2010-06 sample (verified):**
```
SBER;D;20100630;000000;77.7;77.97;76.06;76.5;279914202;0
```
76.5 RUB month-end close — **within 1%** of the legacy CSV anchor (~76).

**SBER monthly 2010-2014 sample (60 rows, 4.4 KB):** returns correct month-OHLC. There is no continuity between the mfd and ISS handoff at the year 2014 (mfd returns data **also after 2014**, which gives us a full overlap region for the regression check).

**Delisted tickers:**
- URKA (Уралкалий): `id=6884` (RTS Classica, USD) and `id=10019` (RTS Standard, USD). **Not a MOEX board** — left the MOEX equivalent before 2014. Mfd.ru **does not store URKA on a MOEX board**.
- POLY (Polymetal pre-redom): `id=512956` and `id=595594` — both return empty datasets for 2013. POLY on MOEX is **absent at mfd up to the current date**; probably ADR/LSE.
- MFON (МегаФон): only ADR Europe (`id=119468`) and RTS Classica (`id=49751`). The MOEX listing 2012-11-28 is **not covered by mfd**.
- MTSI: many IDs, not checked selectively — not critical (MTSI = MTSS predecessor by ISIN, mapping via the bridge policy already exists).

Conclusion on delisted: mfd.ru is good for tickers **continuously listed on MOEX** (SBER, GAZP, LKOH, MTSS, GMKN, NLMK, CHMF, MGNT, ROSN, VTBR, TATN/TATNP, AKRN, AFLT, HYDR, IRAO, ALRS, MAGN). For delisted ones (URKA, POLY, MFON, FIVE pre-redom) — **a separate path, mfd does not close it**.

**Rate limits:** observed no throttling on sequential requests. UA `Mozilla/5.0` + `Referer: https://mfd.ru/export/` is enough. No cookies/auth.

**Adjusted vs raw close:** numbers match MOEX ISS for the overlap 2011-11+ → raw close, **not split-adjusted**. For SBER in 2010-2014 it is not critical (no splits), but VTBR (split 5:1 in December 2007, before our range) and MGNT/NLMK splits after 2010 — our `apply_splits_to_prices` will handle them correctly.

### MOEX ISS — primary, but gap 2010..2011-11

Confirmed `/iss/securities/SBER/aggregates.json` reports the range `2011-11-21..2026-05-11`. Probing SBER on any board (EQBR, TQBR, EQNE, EQDP, RPMA, SMAL) for 2010-06: empty datasets. **ISS physically does not return pre-2011-11-21.** The gap that task 006 is designed for is confirmed.

### finam.ru — blocked by ServicePipe

`https://www.finam.ru/quote/moex/sber/export/` returns HTTP 200 + 1.7KB ServicePipe loader (JS challenge at `servicepipe.ru/static/checkjs/`). `export.finam.ru/table.csv` responds **HTTP 400 with no body** to any parameters (tested with em=3, market=1, p=8 daily, p=10 monthly, 2010-06). It used to work (see `finam-export` PyPI library, last commit 2022) — apparently they moved behind an anti-bot wall between 2022-2026.

**To unblock:** headless Chromium via playwright, passing the JS challenge, extracting cookies `spsn`+`spid`, injecting into curl. This is +a dependency and operational overhead. **Not recommended** given mfd.ru is available.

### T-Bank Invest API

Documentation `developer.tbank.ru/invest/api/market-data-service-get-candles`: `CANDLE_INTERVAL_DAY` has a limit of **up to 6 years in the past** (rolling window from the current date). As of 2026-05: depth back to ~2020-05. **Does not close 2010-2013.** In addition, it requires an API token tied to a brokerage account. Useless for our task.

### Alor Open API

`alor.dev/docs/en/` — OAuth-based, requires a brokerage account. The documentation does not disclose explicit bounds on history depth for equity bars. Even if the depth were >= 16 years — the operational cost (creating an account) is higher than mfd. **Skip.**

### investfunds.ru

The HTML page `/stocks/Sberbank/` returns 200, 344 KB. The chart is rendered by JS via an `/api/` endpoint (exact URL not extracted without a headless render). The quote archive is visible visually from 2002, but **the programmatic path is not verified**. A possible fallback if mfd.ru disappears — requires separate reverse-engineering.

### smart-lab.ru, dohod.ru, conomy.ru

HTML-only, without a programmatic API for prices. Smart-lab annual financial reports, dohod analytical ratings, conomy P&L modeling. **Not prices.**

## 3. Verdict & production recommendation

**Primary: mfd.ru `/export/handler.ashx` GET → CSV.**

Concrete ingest scheme (for task 006 as an addition to the legacy CSV):

1. **Bootstrap ID map**: for each ticker from the universe (`data/canonical/*.yaml`) do GET `mfd.ru/marketdata/search/?ticker_search={SECID}`, parse the HTML, find `id={N}` in the group `МосБиржа Основной`. Cache in `data/ingest/mfd_ticker_ids.json`. Once, ~140 requests.
2. **Fetch loop**: for each ticker GET `/export/handler.ashx/{T}.txt?Tickers={id}&Period=7&StartDate=01.01.2010&EndDate=31.12.2013&RecordFormat=0&FieldSeparator=%3B&DecimalSeparator=.&DateFormat=yyyyMMdd`. Parse TSV-like, convert to `data/prices/{T}.jsonl` in a format compatible with the existing ISS output (BOARDID synthetic="MFD", VALUE=NaN — only OHLCV present).
3. **Merge into pipeline**: handoff at 2011-11-21 — ISS takes priority. Mfd fills 2010-01..2011-11-20 + any gaps >2011-11 for tickers where ISS is thin (e.g. recently listed as of 2011).
4. **Regression**: compare the overlap 2011-11..2014-12 mfd vs ISS at ±2% close-by-close, ±5% volume. If >5% of rows mismatch on the overlap — flag the ticker as unreliable for backfill.
5. **Delisted fallback**: URKA, POLY, MFON, FIVE pre-redom — **mfd does not cover the MOEX board**. Leave as a gap in the universe pre-redom, or ask the user to load manually (`raw_sources/`).

**Advantages vs the current task 006 plan:**
- ✅ Daily not monthly — closes the "monthly-only legacy CSV" limitation.
- ✅ OHLCV+VOL — gives volume for future liquidity filters (task 013 has a screen on volume).
- ✅ Programmatic — no manual CSV in `raw_sources/` for regeneration.
- ✅ Coverage of 174 universe tickers (continuously listed on MOEX) confirmed for SBER, can be validated in a batch.

**Tradeoff:** mfd.ru — a third-party host. If it shuts down — fallback to legacy CSV (already in the repo) + headless finam (operational pain). I recommend keeping fetched mfd CSV in `data/raw/mfd/{T}_{from}_{till}.txt` per the cache-before-validate policy (`feedback_cache_before_validate.md`).

## 4. Unresolved / blocked

| Source | Problem | What is needed from the user |
|---|---|---|
| finam.ru | ServicePipe JS challenge | either a headless Chromium pipeline (extra dep), or manually export CSV from the browser for the needed tickers |
| Tinkoff API | depth 6 years | n/a — a fundamental limitation, cannot be worked around |
| Delisted before MOEX listing (URKA, POLY pre-redom, MFON pre-MOEX) | mfd stores only their LSE/ADR/RTS-Classica data | the user exports the RTS-Classica or LSE archive manually into `raw_sources/`, if these tickers are really needed in the backtest |
| investfunds.ru | API not verified | create a separate task to reverse-engineer the XHR endpoint, if mfd breaks |

**Concrete action item:** in the next iteration of task 006, expand the scope — add an mfd.ru fetcher as a full source for 2010-01..2011-11-20 daily OHLCV. Legacy CSV remains as seed/cross-check. SBER 2010-06-30=76.5 RUB is verified, can be used as an anchor test in `tests/test_mfd_ingest.py`.
