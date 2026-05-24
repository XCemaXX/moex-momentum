# mfd.ru `/export/handler.ashx` — Research Report

Scope: ingest ~150 MOEX equities, ~500–600 GET/run, weekly–monthly cadence. Sources cited inline. Where I couldn't find evidence I say "not found" instead of guessing.

WebFetch was blocked by harness on `mfd.ru/*`, `mfd.ru/privacy`, `mfd.ru/forum/rules/`, `doc.stocksharp.ru/topics/Mfd.html`, and the raw GitHub `rusquant` file. Forum thread `id=13611` is also inaccessible (search index returns nothing — likely old/archived). Everything below is from snippets returned by WebSearch result summaries plus what could be fetched from GitHub `blob` view and one smart-lab page.

---

## 1. Rate limits / throttling

**No documented limit found on mfd.ru.** No public docs, no robots.txt clause referenced anywhere, no `Retry-After` semantics mentioned. What exists is empirical:

- `rusquant` (Vyacheslav Arbuzov, R package on top of `quantmod`) hardcodes a defensive pause: `Sys.sleep(1)` between requests when `>5` symbols are requested. Comment in source: *"pausing 1 second between requests for more than 5 symbols"* (https://github.com/arbuzovv/rusquant/blob/master/R/getSymbols.Mfd.R). 1 rps is the community-accepted ceiling.
- smart-lab blog "Как скачать много котировок акций РФ сразу" (https://smart-lab.ru/blog/620330.php) — author `Camarada` uses mfd as primary source, no mention of bans. Commenter `BVV13`: *"Там слишком любят банить всех налево и направо"* — but context is forum moderation, not the export endpoint. No evidence the export handler itself returns 429 or captcha.
- Forum thread `mfd.ru/forum/thread/?id=13611` referenced in the handler's error message — **not accessible**, not in search index. Cannot confirm contents.

**Verdict:** treat 1 rps as the soft ceiling (rusquant-proven). 600 req at 1 rps = 10 min, fine. No evidence of daily quota. Failure mode is unknown — plan for HTML error page (not JSON) and parse it.

## 2. ToS / redistribution

- `mfd.ru/privacy` and `mfd.ru/forum/rules/` — direct fetch blocked, only summaries available.
- Confirmed via search result excerpt: site states ПАО Московская Биржа owns the exchange data; users **may not redistribute exchange information to third parties without written consent of the Exchange** (no exact quote retrievable). Same clause appears across MOEX-licensed redistributors.
- **No explicit anti-scraping clause found.** No `robots.txt` rule confirmed (couldn't fetch).
- Implication for your pipeline: internal use / personal research = grey but standard. **Publishing the raw OHLCV to GitHub Pages** is the risky part — that is redistribution of MOEX-licensed data. Q-values / derived signals are likely fine; raw bars are not.

## 3. Auth / session

- No login required for `/export/handler.ashx` (rusquant uses plain anonymous GET; smart-lab snippet shows raw URL with no cookies).
- No CSRF token in the URL — rusquant submits straight to `handler.ashx` without first fetching the form. So `__VIEWSTATE`/`__EVENTVALIDATION` (this is an ASP.NET WebForms backend) are **not required** for the GET path.
- `/export/` UI itself is WebForms, but you don't need to POST through it.

## 4. Minimal required parameter set

Confirmed against rusquant source (https://github.com/arbuzovv/rusquant/blob/master/R/getSymbols.Mfd.R). Their working URL template:

```
TickerGroup=<group_id>&Tickers=<ticker_id>&Alias=false
&Period=<p>&timeframeValue=1&timeframeDatePart=day
&StartDate=<dd.mm.yyyy>&EndDate=<dd.mm.yyyy>
&SaveFormat=0&SaveMode=0&FileName=Date18112013_23112013.txt
&FieldSeparator=%3b&DecimalSeparator=.
&DateFormat=yyyyMMdd&TimeFormat=HHmmss
&DateFormatCustom=&TimeFormatCustom=
&AddHeader=true&RecordFormat=0&Fill=false
```

`SaveFormat=0`, `SaveMode=0`, `FileName=<anything>.txt` are present in every public reference implementation. The "При создании файла произошла ошибка" message is consistent with server-side `Response.AppendHeader("Content-Disposition", "attachment; filename=...")` failing when `FileName` is empty — i.e. those three are **required by the handler logic, not optional**.

`TickerGroup` is also load-bearing in rusquant (not just `Tickers`). Your current single-param `Tickers=1463` works because the handler can resolve numeric ID without group context, but rusquant always passes both. Safer to send `TickerGroup` too. I did not find documentation listing all valid `TickerGroup` IDs — rusquant ships them as a static CSV lookup table.

No other hidden required field found. `Alias=false` is the toggle you already discovered (matches your `Tickers=SBER` failure: `Alias=true` would accept the alias).

## 5. Alternatives / SECID

- **`Alias=true` does exist** (rusquant uses `Alias=false` because they have the numeric ID; the param itself is binary). But the alias namespace is mfd's internal aliases, not MOEX SECID. `Tickers=SBER` failing confirms MOEX SECID is not a recognized alias by default.
- **No documented JSON/RSS endpoint for export.** mfd has `tradingsignals/api/http/` but that's a totally different service (trade signals, not market data).
- StockSharp's `S#.MFD` connector (https://stocksharp.com/store/mfd/) wraps the same `handler.ashx` — they did not find a hidden API either, or they'd use it.
- **Conclusion:** the `/marketdata/search/` HTML scrape for `SECID → internal numeric ID` is the only path. Cache the mapping aggressively — internal IDs are stable per security and only change on corporate actions/relisting. rusquant ships a static CSV of mappings for exactly this reason.

## 6. Large window behavior

- No documented response-size limit found.
- 16 years × ~250 trading days = ~4000 daily rows × ~80 bytes CSV ≈ **320 KB per ticker**. Trivial; no chunking needed for daily.
- rusquant pulls full ranges in one shot; no chunking logic in the source.
- Concerns only kick in at minute/tick periods, irrelevant for your daily-OHLCV pipeline.

---

## Practical recommendations

1. **Throttle to 1 rps** with jitter. 600 req → ~10 min, acceptable.
2. **Pin a real browser User-Agent** + `Accept-Language: ru,en;q=0.5`. Default `python-httpx/x.y` UA is a known auto-ban vector on Russian financial portals (general pattern, not mfd-specific confirmation).
3. **Cache the SECID → (TickerGroup, TickerId) map** to a versioned JSON in `raw_sources/`. Refresh only on `Not found` 200-with-error response. Rebuilding the map every run = needless `/marketdata/search/` traffic.
4. **Parse error responses as HTML** — the handler returns 200 + Russian error text, not HTTP error codes. Snippet `"При создании файла"` and `"Не выбрано ни одного тикера"` are your detection strings.
5. **Don't publish raw OHLCV to GitHub Pages** — MOEX licensing clause applies. Publish derived metrics only.
6. **Always send `SaveFormat=0&SaveMode=0&FileName=x.txt`** plus `TickerGroup`. Don't optimize them out.

## Unknowns (need direct probing or user input)

- Exact rate-limit threshold and ban duration — not documented anywhere public. Only way to learn: instrumented probe (not recommended on production IP).
- Forum thread `id=13611` content — couldn't fetch. If user has access, paste contents.
- Full `mfd.ru/privacy` and `mfd.ru/forum/rules/` text — couldn't fetch directly, only summaries.
- Whether mfd returns 429 vs 403 vs HTML-200-with-error on overload — unknown.

## Sources

- https://github.com/arbuzovv/rusquant/blob/master/R/getSymbols.Mfd.R — URL template, throttle pattern
- https://smart-lab.ru/blog/620330.php — community workflow
- https://mfd.ru/export/ — UI (not fetched directly)
- https://mfd.ru/privacy, https://mfd.ru/forum/rules/ — ToS (not fetched directly; summaries only)
- https://stocksharp.com/store/mfd/, https://doc.stocksharp.ru/topics/Mfd.html — S# MFD connector
- https://mfd.ru/forum/thread/?id=13611 — referenced in handler error message; not accessible
