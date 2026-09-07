# Data sources for the momentum pipeline

Outcome of research phase 2. Endpoints verified via curl 2026-05-05.

Base URL: `https://iss.moex.com/iss`. Parameters on every request: `iss.meta=off` (suppresses metadata), `iss.only=<block>` (selects the block). Pagination: `start=N&limit=M` + cursor block `<table>.cursor` with `INDEX/TOTAL/PAGESIZE`. Concurrency ~10 GET without 429.

## 1. Share quotes

```
GET /iss/history/engines/stock/markets/shares/boards/{BOARD}/securities/{TICKER}.json
    ?from=YYYY-MM-DD&till=YYYY-MM-DD&start=N&iss.meta=off&iss.only=history,history.cursor
```

Required columns: `BOARDID, TRADEDATE, OPEN, HIGH, LOW, CLOSE, VOLUME, VALUE`. Confirmed SBER 2024-03-13 close=298.85.

**Survivorship-free ticker list.** Without it the universe is biased.

```
GET /iss/history/engines/stock/markets/shares/listing.json
    ?iss.meta=off&iss.only=securities&start=N
```

Columns `SECID, SHORTNAME, NAME, BOARDID, decimals, history_from, history_till`. A single SECID appears multiple times — one row per board. `delisted_after = max(history_till)` across all boards of the ticker.

**Ticker metadata.** `GET /iss/securities/{TICKER}.json` — block `description` (name/shortname/isin), block `boards` (history of regimes with `is_primary`, `history_from/till`).

**Board fallback.** Request `/boards/TQBR/securities/{TICKER}`; if empty — inspect the `boards` block from metadata, sort by `is_primary desc, history_from asc`, take the first one with a non-empty response. Log loudly `WARN: TICKER fell back to {BOARD}`. Write the `board` field into the JSONL for audit.

**Boundary.** ISS does not return history before 2011-11-21 for SBER (and similarly for other blue chips). For our task (≥13 monthly closes) the start 2012-12+ → 14 years of data, sufficient.

## 2. MCFTRR index

```
GET /iss/history/engines/stock/markets/index/securities/MCFTRR.json
    ?from&till&iss.meta=off&iss.only=history
```

BOARDID=`RTSI` (pseudo-board). Required field — `CLOSE`. Confirmed 2024-03-13 close=6851.42.

**Important.** MCFTRR is a **net** TR index (resident 13% taxes accounted for). Matches our backtest's `DIVIDEND_TAX = 0.13` → the Q1 vs MCFTRR comparison is fair. The gross version — MCFTR (without `R`), we do not pull it.

## 3. Dividends

```
GET /iss/securities/{TICKER}/dividends.json?iss.meta=off    # WITHDRAWN
```

**Dead since roughly 2025-10.** MOEX removed the handle. It answers 200 with the
plain security card (`description` + `boards`) and no `dividends` block; an
invented sub-resource such as `/securities/SBER/zzzznotreal.json` returns the
same bytes, so ISS is discarding the unknown segment rather than erroring.
`/iss/reference/` lists no per-security dividends path, and `/iss/securities/[security]`
has only `aggregates` and `indices` as sub-resources — the handle was never
documented. Re-checked 2026-09-06 against the live reference; prices, index and
splits handles are unaffected. See task 054.

Columns while it lived: `secid, isin, registryclosedate, value, currencyid`. The
fields `declared_date` / `payment_date` were **absent**. Confirmed SBER 2024-07-11 = 33.3 RUB.

SBER coverage over the entire history — 6 records. For long dividend history the coverage is incomplete; the legacy CSV cross-check (phase 12) catches the gaps.

**JSONL format:**
```json
{"registry_close": "2024-07-11", "amount": 33.3, "currency": "RUB", "source": "moex_iss"}
```

The `source` field ∈ `moex_iss | skill_fill_dohod | skill_fill_yahoo | skill_fill_tbank | skill_fill_smartlab | skill_fill_disclosure | manual_disclosure`.

### Which registers closed — the completeness spine

```
GET https://web.moex.com/moex-web-icdb-api/api/v1/export/register-closing-dates/csv?language=1&separator=1
```

First-party MOEX, no auth, cp1251 with no charset header, `MM/DD/YYYY` dates,
whole history in one response. Columns `Эмитент,Дата события,Адрес сайта,Тип события`.
Carries **no amount** — it answers "did this share pay?", not "how much?".

Rows from roughly 2021 embed the SECID and share class in the issuer string
(`… - 2-03-00161-A, TATNP [Акция привилегированная]`), so no name matching is
needed; older rows name the issuer only and are unusable. `Тип события` is
`закрытие реестра` or `закрытие реестра (рекомендуемая)` — the latter is a
recommendation, not an event: SVET/SVETP carry a recommended 2026-07-08 whose
actual closing was 2026-06-01.

Measured against the period where our data was still complete (2024 to 2025-10):
324 register closings on tickers we track, 322 matched a stored payout to the
exact day. That is the check `momentum corporate check-registers` runs.

**Amount sources (via `momentum ingest fill-dividends`):**
- `dohod.ru/ik/analytics/dividend/{ticker_lower}` — deep history, but the index lists ~127 slugs: large caps only. Donor: `WLM1ke/poptimizer_old/src/web/dividends/dohod_ru.py` (archived 2018, needs a smoke test).
- `smart-lab.ru/q/{TICKER}/dividend/` — the only free source reaching the small-cap tail. Both share classes sit in the ordinary share's table; prefs have no page. Amounts are rounded to a few significant digits. Cancelled recommendations stay in the table marked only by a CSS class.
- `e-disclosure.ru` — authoritative, but curl 403, only via WebFetch in manual mode.

**Manual lookup routes** — for one payout at a time, not wired into the pipeline:

- `investfunds.ru/stocks/{slug}/` — server-rendered table with an explicit
  `Закрытие реестра` column next to the ex-date, and **separate pages for preferred
  shares** (`…-pref`). The best single source for settling a disputed figure: it
  covered 8 of the 10 payouts no automated feed had. Deliberately **not** scripted —
  slugs are transliterated company names, not tickers, and are inconsistent
  (`TNS-Energo-Kuban` and `GAZ-service` resolve, `TNS-Energo-Mari-El` and `GAZ-servis`
   404), so automating it would mean hand-maintaining a ticker→slug map.
- `financemarker.ru` — **checked and rejected 2026-09-06, do not use.** Its
  `/legal/terms.pdf` §6.3 forbids automated download and parsing of the service by
  name, and §3.3.9 forbids redistributing the data «в коммерческих или некоммерческих
  целях» and including it in any database. The open `/api/stocks/MOEX:{SECID}/dividends`
  path is an undocumented front-end endpoint that returns more fields than their
  metered paid API, so using it also routes around a paywall. Redistribution is sold
  separately as a commercial tier. Absence of a rate limiter is not consent.
- Issuer disclosure sites. The three gas distributors share a layout:
  `gazcon.ru`, `gaz-services.ru`, `gaz-tek.ru`, PDFs at `rask/<year>/<DD-MM-YY>-<n>.pdf`,
  windows-1251. In the «Начисленные доходы» filing clause 2.8 is the per-share amount
  and clause 2.10 the record date.
- `закрытияреестров.рф` — **dead**, 301 to a parking domain. Do not retry.

Coverage measured 2026-09-06 on the payouts ISS used to carry alone: dohod 2 of
16, tbank 0 of 14, smart-lab 14 of 14.

Sanity check on SBER 2020-2025 (5 points) — MOEX / Smart-Lab / dohod all agree.

## 4. Splits

```
GET /iss/statistics/engines/stock/splits.json?iss.meta=off
GET /iss/statistics/engines/stock/splits/{SECID}.json?iss.meta=off
```

Columns: `tradedate, secid, before, after`. Forward split: `before<after`. Reverse: `before>after`.

**Coverage**: from 2018-12 to 2026-04, 55 rows total (including ETF). Per the 2026-05-05 check — for SBER/GAZP/LKOH/ROSN/MGNT/NLMK/NMTP/MTLR/MTLRP/MDMG/GEMC/CBOM there were **no** splits, the endpoint correctly returns empty.

**Real common-share splits** (filtered out from ETF/`*-RM`/`FIX*`/ISIN):

| tradedate | secid | before:after | type |
|---|---|---|---|
| 2024-02-21 | TRNFP | 1:100 | forward |
| 2024-04-08 | GMKN | 1:100 | forward |
| 2024-07-15 | VTBR | 5000:1 | reverse |
| 2025-03-27 | PLZL | 1:10 | forward |
| 2026-04-17 | T | 1:10 | forward |

**Filtering at ingest:** remove SECID with the `-RM` suffix, the `FIX` prefix, the ISIN format (`RU000A...`). For the final decision — `/securities/{secid}.json` block `description`, keep only `type` ∈ {common_share, preferred_share}.

**Phase 8 convention**: back-adjust to the after scale. A split `(date=D, before=B, after=A)` → coefficient = `B/A` (NOT `A/B`!) multiplies all close prices strictly BEFORE date D. VTBR `(before=5000, after=1)` → coef = 5000 → pre-cons 0.01993 × 5000 = 99.65 ≈ post-cons 92.95 ✓.

**Bonus issues — manual override.** A bonus issue / scrip issue (the company distributes bonus shares for free proportionally to holdings) is **mathematically identical to a split** in its effect on price, but MOEX does not record it in `/splits.json`. BELU 2024-08-20: 7 bonus to 1 → ratio=0.125. The detector will catch this (|return|≈0.875), a manual override in `data/tickers_manual.json` is needed. On TQBR over 2020-2026 — isolated cases.

## 5. Rebrandings

```
GET /iss/history/engines/stock/markets/shares/securities/changeover.json?iss.meta=off
```

Columns: `action_date, old_secid, new_secid`. 637 records since 2003. Confirmed: TCSG→T (2024-11-27), ISKJ→ABIO (2023-08-17), ENRU→ELFV (2023-03-28).

**Covers** technical changeovers — renaming with preservation of SECID/regnumber/legal entity (the SECID simply switches).

**Does NOT cover** redomiciliation / spin-off with a new ISIN — that is legally a new security:

| was | now | date | note |
|---|---|---|---|
| YNDX | YDEX | 2024-07 | redomiciliation NL→RU, new ISIN, **history break** |
| FIVE | X5 | 2025-01 | redomiciliation NL→RU |
| MAIL | VKCO | 2021-12 | rename, no redomiciliation |
| HHRU | HEAD | 2024 | redomiciliation Cyprus→RU |
| POLY | (Solidcore, KZ) | 2024-10 | relocation, delisted from MOEX |
| MDMG-ДР | MDMG | 2024 | redomiciliation |

These cases — in `data/tickers_manual.json` with a mandatory `reason` field.

## 6. Manual override — `data/tickers_manual.json`

One file for all manual cases, unifying two types: bonus issues and redomiciliations. The `reason` field is mandatory — it describes how the case differs from a regular `changeover` or `splits` ingest.

```json
[
  {
    "old_secid": "YNDX",
    "new_secid": "YDEX",
    "renamed": "2024-07-08",
    "type": "redomicile",
    "reason": "NL→RU, новый ISIN RU000A107T19, price history разрывная"
  },
  {
    "old_secid": "BELU",
    "new_secid": "BELU",
    "renamed": "2024-08-20",
    "type": "bonus_issue",
    "ratio": 0.125,
    "reason": "1:8 bonus issue (7 бонусных акций к 1) — gap эквивалентен сплиту, не в /splits.json"
  }
]
```

10-15 cases in total. Filled in manually before the first backtest.

## Outcome: what we ingest

| What | From | Endpoint / file |
|---|---|---|
| Ticker list (survivorship-free) | MOEX ISS | `/iss/history/.../shares/listing.json` |
| Daily quotes | MOEX ISS | `/iss/history/.../boards/{BOARD}/securities/{TICKER}.json` |
| Ticker metadata | MOEX ISS | `/iss/securities/{TICKER}.json` |
| MCFTRR | MOEX ISS | `/iss/history/.../index/securities/MCFTRR.json` |
| Dividend record dates | MOEX web export | `/moex-web-icdb-api/.../register-closing-dates/csv` |
| Dividend amounts | dohod.ru, smart-lab.ru | `momentum ingest fill-dividends` |
| Splits (primary) | MOEX ISS | `/iss/statistics/engines/stock/splits.json` |
| Rebrandings (technical) | MOEX ISS | `/iss/history/.../shares/securities/changeover.json` |
| Bonus issues + redomiciliations | manual list | `data/tickers_manual.json` |

## What was studied and rejected (one line each)

- **investing.com API** — no RUB version without a browser session (Cloudflare 403); USD-ID 23684 gives SBER in dollars, not suitable. Does not return dividends/splits.
- **Tinkoff Invest API** — requires a broker account and token; provides `dividend_net`/`record_date`/`last_buy_date`, but for a monthly backtest these fields are not needed.
- **Finam Trade API** — requires a broker account; no dividends or splits.
- **BCS / Sber Invest / VTB** — no public market-data API.
- **Cbonds / InvestFunds / EODHD** — paid.
- **Smart-Lab forward-dividends parser (poptimizer_old)** — returns expected, not historical; not suitable for our task, for historical we parse `/q/{TICKER}/dividend/` ourselves.
- **`investpy`** — broken after the investing.com API changes of 2022-23. **`investiny`** — does not support Russia.
- **`aiomoex` / `apimoex` / SilverFir donor** — wrappers over the same ISS, drag the extra `aiohttp` into our httpx stack. We will take the pagination pattern from `apimoex/client.py` as a model, but implement it ourselves.
- **`poptimizer_old/src/momentum_tickers.py`** — a different strategy (`gradient/std × volume`), not Q1-Q4. Not an algorithm donor.
- **MOEX `/iss/cci/corp-actions/dividends`** — returns an HTML stub, not public.
- **longterminvestments.ru** — checked 2026-09-06: no per-ticker dividend data at all. Its sitemap is 926 article and portfolio URLs with no ticker route, no screener and no dividend table; guessed routes return an empty shell. Its agreement §3 also forbids automated collection without written permission and §4 forbids derivative databases. A subscription research blog, not a data source.
- **MOEX `/securities/{TICKER}/corporates.json`** — this is just description, not corporate actions; do not confuse them.
</content>
</invoke>
