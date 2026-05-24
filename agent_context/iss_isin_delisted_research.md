# ISS endpoints for ISIN of delisted Russian equities

## 1. Bulk SECID→ISIN including delisted

```
GET https://iss.moex.com/iss/securities.json?engine=stock&market=shares&is_trading=0&securities.columns=secid,isin,is_traded,type,primary_boardid&iss.meta=off&start={N}
```

- Pagination: 100 rows/page, increment `start` by 100. Verified: `start=0`, `100`, `500`, `1000`, `1500` each return 100; `start=2000` empty. Full delisted universe ≈ 1500–2000 rows (incl. ETF/PIF/depositary_receipt — filter on `type=common_share`/`preferred_share`).
- Same URL without `is_trading=0` returns only currently-tradable rows (which is what the existing universe endpoint does). Toggle `is_trading=0`/`is_trading=1` to split. **Param name is `is_trading` (input), column name is `is_traded` (output) — not a typo.**
- Response shape: `data.securities.{columns,data}`. ISIN at column index `1` when `columns=secid,isin,...`.

## 2. Single-SECID lookup that works for delisted

```
GET https://iss.moex.com/iss/securities/{SECID}.json
```

- Response: `data.description.data` is `[name,title,value,...]` rows; pick the row where `name=="ISIN"` → `value`. Test results (verified by curl 2026-05-13):

| SECID | ISIN | NAME |
|---|---|---|
| URKA | RU0007661302 | Уралкалий ПАО ао |
| MFON | RU000A0JS942 | МегаФон ПАО ао |
| ARMD | RU000A0JP4J4 | АРМАДА ПАО ао |
| SCON | RU000A0DM8R7 | Седьмой Континент ОАО |
| OMSB | RU000A0HG9A5 | Омскэнергосбыт ОАО ао |

- Also returns `boards` block with `is_traded`, `history_from`, `history_till` per board — useful for redomicile/board-migration analysis.

## 3. Targeted search (alternative to full bulk)

```
GET https://iss.moex.com/iss/securities.json?engine=stock&market=shares&is_trading=0&q={QUERY}&securities.columns=secid,isin,is_traded,type,primary_boardid&iss.meta=off
```

`q` matches against SECID/name. All 5 test SECIDs found. Hits include legacy duplicates (e.g. `URKA-004D`, `SCON-2005`) — filter on `type` and exact-match SECID.

## Limitations / caveats

- **ISIN is current-value only**, not historical. If MOEX changed an ISIN mid-life (rare for RU equities), this endpoint shows only the latest. For sample test cases all ISINs are stable.
- `/iss/history/engines/stock/markets/shares/securities.json?date=YYYY-MM-DD` returns OHLCV per board for that date but **does NOT include ISIN** — only `SECID`, `SHORTNAME`, `BOARDID`. Useless for ISIN backfill.
- Pagination is hardcoded 100/page; passing `limit=N` does not increase page size on `/iss/securities.json` reliably.
- The existing `/iss/engines/stock/markets/shares/securities.json` endpoint is board-scoped (returns only securities currently admitted to a board) — that's why it misses delisted. Use `/iss/securities.json` (no engines/markets path prefix) plus `is_trading=0` filter instead.

## Citations

- https://iss.moex.com/iss/reference/5 (`/iss/securities`)
- https://iss.moex.com/iss/reference/13 (`/iss/securities/[security]`)
- https://iss.moex.com/iss/reference/41 (`/iss/history/engines/[engine]/markets/[market]/securities`)
