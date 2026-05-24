# mfd.ru reputation + RU price-source alternatives

Scope: validate whether `mfd.ru/export` is a trustworthy production source for daily OHLCV (2010+) and enumerate other RU sources. WebFetch was denied in this session; findings rely on WebSearch result summaries and prior project research. Treat every claim below as needing one round-trip smoke-test in a follow-up before wiring in.

## 1. mfd.ru trust verdict: MEDIUM (use as fallback / cross-check, not primary)

Rationale:
- **Operator is a real, long-lived company.** ООО «МФД-ИнфоЦентр» registered 24.10.1996 (Moscow, ИНН 7727107905); a second entity «МФД-ИнфоЦентр Плюс» registered 2007. ~30 years of continuous operation in financial-information software for banks/brokers. Not a hobbyist site.
- **Ownership is identifiable but non-institutional.** Public registries (rusprofile, rbc.companies, spark-interfax) list Гарегин Тосунян 60% / Жанна Куликова 40% as current beneficiaries. Tosunyan is a known figure (former head of Association of Russian Banks). Not a state-affiliated SRO, no Bank of Russia accreditation found — they are an info-aggregator, not a regulated venue.
- **Community standing is established but second-tier.** Smart-lab threads explicitly recommend migrating from finam.ru to mfd.ru after Finam removed archive export ("Финам закрыл экспорт архивных котировок"). The R `rusquant` package exposes a dedicated `getSymbols.Mfd` backend alongside `getSymbols.Moex` / `getSymbols.Finam`, and StockSharp (`doc.stocksharp.ru/topics/Mfd.html`) ships a first-class Mfd connector. That is meaningful third-party endorsement.
- **Data lineage is exchange-sourced but unlicensed for redistribution.** Forum pages carry the standard "PAO Moskovskaya Birzha is source/owner" notice, but mfd.ru does **not** appear on MOEX's official market-data distributors list. They redistribute on the basis of delayed/end-of-day data, which MOEX allows under its public data policy for non-commercial display but **not formally** for bulk redistribution to third parties. Legal risk is real but historically not enforced against them.
- **Track record of outages but no signal of imminent shutdown.** Public outage trackers (downradar.ru, nerobit.ru) show recurring 503s including a notable cluster Aug–Sep 2024. No reports of takedowns, ownership changes, or business-model pivots in the last 12 months. Domain is paid through, site is alive May 2026.

Bottom line: trustworthy enough to mirror as a fallback, **not** trustworthy enough to be the single primary source for a production pipeline. The combination of (a) no MOEX distributor agreement, (b) recurring 503 outages, and (c) a single small private operator is enough risk to require a primary that you control more tightly.

## 2. Production risks for mfd.ru

- **ToS/redistribution risk.** No explicit "free for commercial use" clause was found in `mfd.ru/forum/rules/` (search-only access). MOEX's data policy requires a distributor agreement for any onward redistribution. If you republish raw mfd CSVs in `docs/pages/*`, you re-publish exchange-owned ticks without a licence chain. Probability of takedown letter to a personal GH Pages site is low, but non-zero if traffic spikes.
- **No rate-limit doc, no SLA.** mfd doesn't publish quotas. `service@mfd.ru` is the only contact. Historic bulk-download threads on smart-lab describe trial-and-error throttling. Expect silent IP bans on aggressive parallelism — single-thread, sleep-between-requests.
- **No documented API contract.** The `/export/` endpoint is an ASP.NET handler (`.ashx`) with query-string params (`Alias`, `Period`, `StartDate`, `EndDate`, `SaveFormat`, etc.) that have changed in the past. There is no versioning, no deprecation policy. Schema can break unannounced.
- **Single operator, no redundancy.** One company, one domain, one team. The 2024 503 episode lasted weeks. If they fold, all backfill capability evaporates.
- **Encoding/format quirks.** Output is windows-1251 by default, semicolon-separated, RU decimal commas unless params are set. Easy to misparse silently into off-by-100x errors.
- **No corporate-actions stream.** mfd.ru gives prices, not dividends/splits adjusted. For momentum you don't need adjustments, but if scope ever expands to total-return you'll need a separate source.

## 3. Alternative RU sources

| Source | Auth | Depth | Free/Paid | Cross-check SBER 2010-06-30 | Recommendation |
|---|---|---|---|---|---|
| **MOEX ISS** (`iss.moex.com/iss/history/...` and `/candles`) | None | SBER from 2007 on TQBR; older boards back further | Free, official | Authoritative — anchors all other sources | **PRIMARY.** Already used in project per `agent_context/data_sources.md`. 1000-row page cap, plain REST, stable since ~2013. |
| **mfd.ru `/export/`** | None | Equities/futures from ~1998 depending on instrument; SBER 2010 confirmed previously (76.5 RUB anchor) | Free, no formal licence | Verified by user in prior research | **FALLBACK** for legacy backfill or ISS-gap reconciliation. |
| **finam.ru `/export/`** | None (manual); auto blocked | Used to go back to 2000s; archives partially deleted in 2023–2024 | Free for manual, "automated import forbidden" per ToS | N/A — service no longer reliable | **SKIP.** Smart-lab confirms "Финам закрыл экспорт архивных котировок" and 403s on automated calls. Community has already migrated off it. |
| **alor.dev** (`/md/v2/history`) | Optional; unauth returns 15-min-delayed data | Limited — daily candles go back several years, not to 2010 reliably | Free for unauth, full requires brokerage account | Likely no 2010 coverage | **SKIP for backfill, KEEP for live.** Useful if pipeline ever extends to intraday/streaming, not for historical depth. |
| **Tinkoff/T-Invest API** (`investAPI`) | Token required (brokerage account) | Candles back ~10 years for major tickers | Free with account | Account-gated — cannot smoke-test anonymously | **SKIP** unless user already holds a T-Invest token. Adds a credential dependency. |
| **БКС / Сбер Инвестиции / Открытие** | Account + app required | Mobile-app-only chart data, no documented public API | Free with account | Unverifiable without sign-up | **SKIP.** No public unauth endpoint surfaced in any search. |
| **Cbonds API** (`cbonds.com/api/stocks`) | API key after application | Deep, validated, includes corporate actions | Paid ($350–1000/mo); 2-week trial on ~10–15 instruments | Trial only | **SKIP** unless budget exists. Quality is high, terms are commercial. |
| **investfunds.ru** | None | Per-ticker pages exist for MOEX names | Free, browser-oriented; bulk download not documented | Not verified | **SKIP.** Looks like a screen-scrape target, not a feed. Effort > value when ISS works. |
| **conomy.ru** | None | Fundamental-data focus; price archive not advertised | Free | Not in search index for OHLCV download | **SKIP.** Wrong domain (fundamentals, not OHLCV exports). |
| **bcs-express.ru** | None | News/charts only, no documented CSV export | Free | No export endpoint found | **SKIP.** Editorial site, not a data feed. |
| **profinance.ru** | None | Macro/FX charts | Free, charts-only | No equity OHLCV download | **SKIP.** Wrong asset class focus. |
| **arsagera.ru** | None | Their own fund NAV history | Free | Not a general-equity feed | **SKIP.** Asset manager, not a data vendor. |
| **Yahoo Finance** (`SBER.ME`) | None | From 2007 | Free | Reproduces ISS for daily close | Already covered in `price_sources_research_intl.md`. Not a "RU source" but viable backstop. |
| **rusquant R package** | None | Aggregates Moex/Mfd/Finam | Free | Same data as upstream | Reference implementation only — pipeline is Python, do not adopt R dependency. |
| **QUIK historical dumps** | Requires QUIK install + broker | Variable | Free with broker | No anonymous CSV mirror | **SKIP.** Each broker's QUIK feed is locally cached; no community-wide dump exists. |
| **GitHub community dumps** (`nerevar/stock_prices`, `ffeast/finam-export`, `WISEPLAT/backtrader_moexalgo`) | None | Snapshot at repo-commit time | Free | Stale, not maintained as feeds | **SKIP as runtime source**, mine for ticker-mapping seed data only. |
| **НИУ ВШЭ / academic** | Varies | Sporadic datasets | Free / paywall | No general OHLCV repo found | **SKIP.** No discoverable open dataset matching scope. |

## 4. Recommendations

- **Primary: MOEX ISS.** Already in scope, official, free, no licence ambiguity, 2007+ depth covers all stated requirements. Live with the 1000-row pagination cap — it's trivial to chunk.
- **Cross-check / fallback: mfd.ru.** Wire it as a *secondary* validator: pull SBER (and 3–5 other anchor tickers) for a handful of historical dates, assert ISS close == mfd close within tolerance. If ISS goes down or returns suspicious gaps, mfd is the only no-auth deep-history source left after Finam closed its archive. **Do not** make mfd the load-bearing source.
- **Skip everything else for backfill.** Finam is dead for automation, Alor lacks depth, broker APIs need accounts, Cbonds costs money, the rest are either screen-scrape targets or wrong-asset-class.
- **Keep alor.dev on the radar for live/intraday extensions only** (current scope is end-of-day, so not now).
- **Do not redistribute raw mfd CSVs** on the GitHub Pages output. Republish only derived/aggregated values (quartile assignments, momentum scores) and link out for raw prices. Cuts the redistribution-licence question off at the source.

## Caveats

- WebFetch was denied this session, so the SBER 2010-06-30 = 76.5 RUB anchor was **not** re-verified against mfd in this run — it relies on prior project verification cited in the request. Re-confirm with a one-shot HTTP smoke before committing.
- "No outages" / "no ToS issue" claims rest on absence-of-evidence in search summaries, not direct ToS reading. Read `mfd.ru/forum/rules/` and `mfd.ru/export/help/` manually before any public republication of raw data.
- Russia-internet geopolitics is volatile. Any RU-domain source can become unreachable from non-RU IPs without notice. Plan for mirror-to-S3 / mirror-to-repo of pulled bars on first successful fetch — don't assume re-fetchability.
