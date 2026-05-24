# External ISIN sources for delisted Russian shares

Note: WebFetch was permission-denied for most domains during research. Evidence below comes from Google SERP snippets that already include ISIN inside result titles. URL patterns are confirmed but full-page parsability for bulk scraping is NOT verified end-to-end. Spot-check before committing to any scraper.

## Top recommendations

### 1. Bulk universe — OpenSanctions `ru_nsd_isin` (recommended starting point)

- Mirrors NSD's full Russian ISIN registry
- Daily updates, free CC license
- Bulk CSV/JSON download
- URLs:
  - https://www.opensanctions.org/datasets/ru_nsd_isin/
  - https://data.opensanctions.org/datasets/latest/ru_nsd_isin/
- **Caveat**: schema field for MOEX SECID is UNVERIFIED — must `head -1` of the actual file after download to confirm

### 2. Name-keyed lookup — investfunds.ru

- Embeds ISIN directly in HTML `<title>` tag
- URL pattern: `https://investfunds.ru/stocks/{Latin-Slug}/`
- Slug is descriptive English (e.g. `Uralkali`, `Seventh-Continent`, `Omskenergosbyt`)
- Covers delisted shares
- Easy to scrape — just GET + regex `RU[0-9A-Z]{10}` from the title

### 3. ISIN-keyed verifier — cbonds.com

- URL pattern: `https://cbonds.com/stocks/{ISIN}/`
- Use to verify ISIN once you have a candidate
- Confirmed live for `RU0007661302` (URKA), `RU000A0JR4A1` (MOEX)

## Coverage matrix — 5/5 test SECIDs found

| SECID | ISIN | Source |
|-------|------|--------|
| URKA  | RU0007661302 | cbonds.com + investfunds.ru |
| MFON  | RU000A0JS942 | investfunds.ru (title) |
| ARMD  | RU000A0JP4J4 | fin-plan.org `/lk/actions/RU000A0JP4J4/` |
| SCON  | RU000A0DM8R7 | investfunds.ru `/stocks/Seventh-Continent/` |
| OMSB  | RU000A0HG9A5 | investfunds.ru `/stocks/Omskenergosbyt/` (title) |

## Anti-recommendations

- **smart-lab.ru** — returns 404 on `/q/{SECID}/` and shows no ISIN even on working pages
- **OpenFIGI free tier** — likely undercovers RU delisted small-caps (25 req/min, mostly US-centric data)
- **nsd.ru / nsddata.ru** — no documented free API; paid only
- **Broker sites (finam, tinkoff)** — hide ISIN behind JS/auth

## Suggested integration

1. Download OpenSanctions `ru_nsd_isin` once → build `{ISIN: issuer_name}` table
2. For our 1900 mfd ISINs not yet matched: Google `site:investfunds.ru "{russian_name}"` + regex `RU[0-9A-Z]{10}` from result snippets
3. Verify residuals via `cbonds.com/stocks/{ISIN}/`

## Direct citations

- https://cbonds.com/stocks/RU0007661302/
- https://cbonds.com/stocks/RU000A0JR4A1/
- https://investfunds.ru/stocks/Uralkali/
- https://investfunds.ru/stocks/Megafon/
- https://investfunds.ru/stocks/Omskenergosbyt/
- https://investfunds.ru/stocks/Seventh-Continent/
- https://investfunds.ru/stocks/Armada/
- https://fin-plan.org/lk/actions/RU000A0JP4J4/
- https://www.opensanctions.org/datasets/ru_nsd_isin/
- https://data.opensanctions.org/datasets/latest/ru_nsd_isin/
- https://www.openfigi.com/api/documentation
