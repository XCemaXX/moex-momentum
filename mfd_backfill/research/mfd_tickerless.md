# mfd.ru tickerless entries — research

Date: 2026-05-13. Scope: should the mfd.ru ID→SECID resolver skip pages where the "Код" field is missing?

## 1. What "Код" represents

The "Код" field on `mfd.ru/marketdata/ticker/?id=N` is the **trading code (SECID)** as used in the underlying venue's order book — same notion MOEX ISS calls `SECID`. For MOEX equities it is the Latin ticker (SBER, GAZP, MAGN); for RTS Classica entries on the same site the code is the RTS Latin ticker (e.g. `MAGN`, `PMTL`, `RUIB`). mfd carries the same security under **multiple internal IDs**, one per venue/board (e.g. MAGN: id=6531 on RTS Classica, separate id under МосБиржа Акции group=16) ([mfd MAGN RTS](https://mfd.ru/marketdata/ticker/?id=6531), [smart-lab on delisted](https://smart-lab.ru/blog/560563.php)). So "Код" is not a MOEX-wide identifier — it is whatever code the venue used for that listing.

## 2. Why "Код" is missing

The three sample tickerless IDs (68, 69, 1000) all correspond to securities that DO have MOEX SECIDs in our local `data/tickers.json` (SCON, ARMD, OMSB respectively), with confirmed delisting dates 2012–2019. So "missing Код" is not "no SECID ever existed". Top reasons:

1. **mfd has multiple records per security; the tickerless one is the non-MOEX or pre-2011-merger venue entry.** ARMD/SCON/OMSB traded on MICEX/RTS legacy boards (EQNE/EQNL/SMAL/TQNL/EQDE) — never TQBR. The MOEX-aligned entry under TickerGroup=16 carries Код; the legacy/RTS-side entry does not. Evidence: same security appears under two ids in mfd search results ([investfunds SCON](https://investfunds.ru/stocks/Seventh-Continent/), [investfunds ARMD](https://investfunds.ru/stocks/Armada/), [moex.com SecuritiesListing](https://www.moex.com/ru/SecuritiesListing.aspx)).
2. **Legacy / data-entry omission.** Some MICEX-era entries imported before mfd standardised the schema simply have no Latin code populated. The field is optional in the page template — Russian shortname + ISIN are always rendered, Код only when the feed supplied it.
3. **Pure-OTC or indicative-only listings.** MOEX Board indicative quotation system covers securities "not publicly available on the Russian organized market" ([MOEX Board](https://www.moex.com/moexboard/)) — those rows have no order-book SECID by construction.

Hypothesis (c) (preferred shares of obscure regionals) is **not supported** — preferred shares get explicit `*P` SECIDs (OMSBP exists). Hypothesis (a) (pre-uniformity) is partially true but subsumed by (1)+(2).

## 3. Recommendation

**Skip tickerless mfd entries for a 2010+ TQBR-quality momentum universe. Confidence: high.**

Reasoning:
- Your universe is sourced from MOEX ISS canonical SECIDs (`data/tickers.json`), not from mfd. mfd is only a price source for the 2010–2011-11 gap (task 006).
- Every MOEX-listed security worth including has at least one mfd entry with Код populated — the resolver matches on SECID, so missing-Код entries are either duplicates of the same security on another venue or genuinely non-MOEX rows. Both should be discarded.
- The risk of losing a TQBR-quality 2010+ name to this filter is near zero: any equity liquid enough to enter a momentum universe traded on a Latin-SECID-bearing MICEX/MOEX board after 2010 and will have a Код-bearing mfd record.
- Edge case: securities that traded *only* on EQNL/EQDE/SMAL boards (third-level, deep illiquid). Those should already be excluded by liquidity filters upstream, regardless of mfd coverage.

Action: in the resolver, drop rows without Код silently; log count but do not warn per-row.

## Sources

- https://www.moex.com/ru/SecuritiesListing.aspx
- https://mfd.ru/marketdata/ticker/?id=6531 (MAGN RTS Classica — separate id)
- https://investfunds.ru/stocks/Seventh-Continent/ (SCON delisting 2012-09-28)
- https://investfunds.ru/stocks/Armada/ (ARMD ticker, level-3 listing, IPO 2007-11-30)
- https://www.moex.com/moexboard/ (indicative-only quotes context)
- https://smart-lab.ru/blog/560563.php (list of delisted MOEX equities)
- en.wikipedia.org/wiki/Moscow_Exchange (MICEX+RTS merger 2011-12-19)
