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
GET /iss/securities/{TICKER}/dividends.json?iss.meta=off
```

Columns: `secid, isin, registryclosedate, value, currencyid`. The fields `declared_date` / `payment_date` are **absent**. Confirmed SBER 2024-07-11 = 33.3 RUB.

SBER coverage over the entire history — 6 records. For long dividend history the coverage is incomplete; the legacy CSV cross-check (phase 12) catches the gaps.

**JSONL format:**
```json
{"registry_close": "2024-07-11", "amount": 33.3, "currency": "RUB", "source": "moex_iss"}
```

The `source` field ∈ `moex_iss | skill_fill_dohod | skill_fill_smartlab | manual`.

**Fallback (via skill `/fill-dividends`):**
- `dohod.ru/ik/analytics/dividend/{ticker_lower}` — table "Announcement date / Record date / Year / Dividend". Without explicit CSS classes. Donor: `WLM1ke/poptimizer_old/src/web/dividends/dohod_ru.py` (archived 2018, needs a smoke test).
- `smart-lab.ru/q/{TICKER}/dividend/` — for reference, for cross-check.
- `e-disclosure.ru` — authoritative, but curl 403, only via WebFetch in manual mode.

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
| Dividends (primary) | MOEX ISS | `/iss/securities/{TICKER}/dividends.json` |
| Dividends (fallback) | dohod.ru, smart-lab.ru | via skill `/fill-dividends` |
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
- **MOEX `/securities/{TICKER}/corporates.json`** — this is just description, not corporate actions; do not confuse them.
- **`web.moex.com/moex-web-icdb-api/api/v1/export/register-closing-dates/csv`** (CP1251) — forward-looking registries. Useful for displaying "a record date is coming up", but not needed for a historical backtest. Optional for the future.
</content>
</invoke>
