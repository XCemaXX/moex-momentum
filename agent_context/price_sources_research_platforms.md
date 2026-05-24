# Bundled / Addon Data Feeds in Backtesting Platforms — MOEX Coverage 2010–2014

Scope: feeds shipped with or pluggable into WealthLab, AmiBroker, TSLab, Tradematic Trader, MultiCharts.
Goal: find a programmatic, license-independent source filling the MOEX ISS gap 2010-01-01 → 2011-11-21 for SBER + ~20 priority tickers.
Anchor: SBER 2010-06-30 close = **76.50 RUB** (verified live against mfd.ru CSV API today, 2026-05-12; see end).

---

## 1. Summary table

| Platform          | Bundled data feed                                          | Programmatic without license? | MOEX depth (SBER)       | Cost          | Anchor cross-check 76.5 ±1% |
|-------------------|------------------------------------------------------------|-------------------------------|-------------------------|---------------|-----------------------------|
| WealthLab         | Russia Extension: Finam + MFD + MOEX + QUIK providers      | **Yes (indirectly)** — providers wrap public sites | Down to ~2000 (Finam/MFD) | Free | Verified via mfd.ru (provider just wraps it): **76.50** |
| AmiBroker         | ASCII importer / AmiQuote / Q2Ami QUIK plugin              | Yes (ASCII) / No (Q2Ami needs QUIK terminal) | Q2Ami: only what QUIK serves (broker-dependent, usually ≤ ~5y) | Free plugins; AmiBroker license $339 | Not bundled with prices — pulls from same upstream (Finam/QUIK) |
| TSLab             | Three modes: Finam .txt, Finam .csv, online providers (QUIK/Plaza/MFD via NetInvestor) | No — TSLab expects files on disk; user fetches separately | Whatever Finam UI returns (~2000–) | Platform paid; data free | NA — TSLab itself doesn't host data |
| Tradematic Trader | Broker terminals (QUIK, Transaq, etc.) + user-loaded text dumps | No — needs QUIK/Transaq connection; broker-side history limited | Broker dependent, typically ≤ 3–5y | Paid platform | NA |
| MultiCharts       | QUIK plugin, IQFeed, Interactive Brokers, CQG, Continuum  | No — feeds tied to MC license/broker account | QUIK: ≤ broker retention; IQFeed: no MOEX; IB: no MOEX equities post-2022 sanctions | MC $1,497 + feed fees | NA — none ships MOEX equity history pre-2012 |

**Bottom line**: not one of the five platforms ships its own MOEX equity archive. They all wrap upstream public sources (Finam, mfd.ru, MOEX ISS, QUIK broker servers). The only useful by-product is the **WealthLab Russia Extension source code**, which documents the same mfd.ru / Finam endpoints we already use.

---

## 2. Per-platform notes

### 2.1 WealthLab (wealth-lab.com)
- **Russia Extension** (current build 14, free): bundles four data providers — Finam, MFD, MOEX ISS, QUIK.
  - Finam provider — wraps `finam.ru/profile/...` export endpoint. As of 2024–2025 this endpoint is gated by **ServicePipe anti-bot**, so a parallel agent already confirmed it returns HTTP 400 from non-browser clients. WealthLab works because it ships a desktop user-agent + cookie flow; standalone replication needs full browser emulation (Playwright/undetected-chromedriver). Not free-cost.
  - MFD provider — wraps `mfd.ru/export/handler.ashx`. **No anti-bot**, no auth — exactly the endpoint already used in `price_sources_research.md`.
  - MOEX provider — calls `iss.moex.com`. Same hard floor 2011-11-21 we already hit.
  - QUIK provider — requires running QUIK terminal of a Russian broker; pulls whatever history that broker's server stores (typically rolling 3–5 years), not deep historical.
- Symbology: native ticker (`SBER`, `GAZP`, `LKOH`), no exchange suffix. Finam provider expects the Finam emitent code (`SBER`/`SBER@MICEX` historically) — the Nov 2025 forum thread is about handling duplicate symbols across boards.
- Source code is **C# .NET**, the wiki pages (`www2.wealth-lab.com/wl5wiki/MfdProvider.ashx`, `FinamStaticProvider.ashx`) document parameter names. Useful as a spec, not as a feed.
- Verdict: same upstream we already use. No deeper coverage.

### 2.2 AmiBroker (amibroker.com)
- AmiBroker itself is a database + scripting engine — **no bundled price data**.
- AmiQuote (built-in downloader) supports: Yahoo, Tiingo, Google, Finam (forex only per docs), Norgate. No MOEX equity coverage.
- **Q2Ami** (github.com/Arech/Q2Ami) — community plugin: pulls real-time from a running QUIK terminal via `t18qsrv` proxy. NO historical backfill — author's README explicitly says "no backfill in DDE/plugin; use ASCII importer for history first".
- Norgate Data — confirmed US/Australia/Canada equities + futures/FX. No Russian coverage in 2025.
- ASCII importer is universal — accepts the Finam `<DATE>,<TIME>,<OPEN>,<HIGH>,<LOW>,<CLOSE>,<VOL>` layout out-of-the-box with `$FORMAT` directives.
- Verdict: doesn't ship data; will ingest whatever you give it. Irrelevant for sourcing.

### 2.3 TSLab (tslab.ru / doc.tslab.pro)
- Per Russian tutorials (daytradingschool.ru, trader-nt.ru, doc.tslab.pro) TSLab understands **three** kinds of historical sources:
  1. Text files (.txt) exported manually from Finam UI (`finam.ru/profile → Экспорт котировок`, i.e. the "Export quotes" menu item).
  2. CSV files from Finam.
  3. Online providers — QUIK / Plaza II / TRANSAQ / NetInvestor (MFD's history server).
- Required Finam export params for TSLab: format=txt, date=yyyymmdd, time=hhmmss, MSK timezone, comma delimiter. Standard Finam ASCII.
- TSLab **does not host or bundle** archives. Users still go to finam.ru by hand.
- The "free quote downloader" tools cited on smart-lab.ru (e.g. blog/212186) are user scripts that scrape finam.ru, not platform features.
- Symbology: same as Finam — `SBER`, `GAZP`, etc. by emitent code.
- Verdict: pure consumer of the same upstream. The Finam txt format reference is mildly useful documentation; the platform itself contributes nothing.

### 2.4 Tradematic Trader (tradematic.com)
- Per opexflow.com / fsr-develop.ru reviews: trading via **QUIK, Transaq, MetaTrader** connectors. >10 partner brokers. >12 venues including MOEX.
- Historical-data design (per tradematic.com/docs description): "datasource manager lets you backtest on history from broker server **or text data obtained from different sites**" — i.e. user-supplied CSVs. Identical model to TSLab.
- No bundled MOEX archive. No public CSV dump. No standalone API.
- Tradematic Cloud is a B2B platform — paid, no free historical tier.
- Verdict: same as TSLab; not a data source.

### 2.5 MultiCharts (multicharts.com)
- Official **QUIK plugin** (released ~Nov 2011, still maintained). Connects MultiCharts to running QUIK terminal. History limited to what the broker's QUIK server returns — typically ≤ 3 years for equities, can be near-zero for deep history. No public archive.
- Other feeds bundled (IQFeed, Interactive Brokers, CQG, Continuum, Rithmic) — **none cover MOEX-listed Russian equities** post-2022 sanctions (IB delisted Russian equities; IQFeed never had them).
- Cannot fetch QUIK plugin's data without a MultiCharts license **and** an active QUIK broker connection.
- Symbology in QUIK plugin: `SBER` on board `TQBR`, futures `SRH3` etc. on `SPBFUT`.
- Verdict: irrelevant for free historical pre-2012.

---

## 3. Verdict

**None of the five platforms provides a better SBER 2010–2011 source than mfd.ru.** All five either:
- (a) wrap mfd.ru / finam.ru / MOEX ISS — i.e. the same sources we already evaluated, or
- (b) defer entirely to broker servers (QUIK, Transaq) that store at most rolling 3–5 years of history.

Concretely, the WealthLab Russia Extension is the **best confirmation** that mfd.ru is the canonical free deep-history feed for Russian equities — a commercial product targeted at Russian retail quants chose mfd.ru as one of four providers and didn't add a fifth deeper archive, because none exists in the public domain.

**Action**: Stick with mfd.ru (already validated, 76.50 anchor matches). Don't waste cycles on platform-specific feeds — they don't have anything we don't already have, and most require paid licenses or active broker accounts.

**Marginal value** from this round of research:
- WealthLab wiki pages (`MfdProvider.ashx`, `FinamStaticProvider.ashx`) are a free spec reference for the mfd.ru / finam.ru export URL parameters.
- AmiBroker's `$FORMAT` ASCII importer is a known sink format if we ever need to write MetaStock/AmiBroker-compatible exports.

---

## 4. Cross-platform data formats worth knowing

### Finam ASCII (the lingua franca)
```
<TICKER>,<PER>,<DATE>,<TIME>,<OPEN>,<HIGH>,<LOW>,<CLOSE>,<VOL>
SBER,D,20100630,000000,77.10,78.43,76.05,76.50,279914202
```
- `<PER>`: `1` tick, `5` 5-min, `60` hourly, `D` daily, `W` weekly, `M` monthly.
- Date format **yyyymmdd**, time **hhmmss**, separator usually comma but Finam UI lets you pick.
- Period code `7` in the mfd.ru handler URL = daily (per existing `data_sources.md`).

### mfd.ru CSV (confirmed live today)
- Endpoint: `https://mfd.ru/export/handler.ashx/data.csv?TickerGroup=16&Tickers={id}&Period=7&StartDate=DD.MM.YYYY&EndDate=DD.MM.YYYY&...`
- **Date must be DD.MM.YYYY** in request (parameter), output is `yyyy-MM-dd` if `DateFormat=yyyy-MM-dd` is passed. The query parser rejects ISO yyyy-MM-dd in `StartDate`.
- Columns: `<TICKER>;<PER>;<DATE>;<TIME>;<OPEN>;<HIGH>;<LOW>;<CLOSE>;<VOL>;<OPENINT>` (semicolon-separated, ticker column is the Russian display name e.g. `Сбербанк`, not the symbol — use the `Tickers=` numeric id for joining).
- SBER id=1463 on MOEX board. Other ids on the same domain: `mfd.ru/marketdata/ticker/?id={N}`.

### MetaStock binary (.DAT + EMASTER/MASTER)
- Microsoft Binary Format floats (MBF), 4 bytes — not IEEE-754; converters required (`ms2txt`, `metastock2pd`, `meta-api` on PyPI).
- mfd.ru exposes MetaStock-format export at `mfd.ru/export/` as alternative to CSV. Don't use it; CSV path is simpler and identical content.
- AmiBroker and MultiCharts both natively read MetaStock; not relevant to our Python pipeline.

### WealthLab Russia Extension (`.WL5` data files)
- Proprietary binary, only readable by WealthLab. Not useful outside the platform.

---

## Live verification log (2026-05-12)

Single curl to mfd.ru, no auth, no anti-bot:
```
curl 'https://mfd.ru/export/handler.ashx/data.csv?TickerGroup=16&Tickers=1463&Period=7\
&StartDate=28.06.2010&EndDate=02.07.2010&DateFormat=yyyy-MM-dd&...'
```
Output snippet:
```
Сбербанк;D;2010-06-30;00:00:00;77.1;78.43;76.05;76.5;279914202;0
```
**SBER 2010-06-30 close = 76.50 RUB** — matches anchor exactly. mfd.ru remains the only free, no-auth, programmatically accessible deep-history source for MOEX equities. No platform among the five investigated improves on this.
