# Reference CSV — known defect catalog

Compiled from task 016 web-verification of `raw_sources/Российские_акции_дивиденды.csv` cells. The CSV is the user's hand-curated 1611-cell anchor used by `validate_with_raw/` for coverage measurement — NOT a source of truth. Future tasks should treat any divergence between web disclosure sources and this CSV as CSV-side defect first.

Each defect class below is documented so the next pass doesn't re-discover.

## Year-typo (6 cells)

Cell registered in CSV under wrong year; real event in different year, same month-day.

| Ticker | CSV cell | Real registry | Diagnostic |
|---|---|---|---|
| QIWI | 2016-03 / 35.44 | 2017-03-29 / 34.27 | Smart-lab has no Mar 2016 payout; 4кв 2015 special paid late |
| POSI | 2025-05 / 47.33 | 2024-05-24 / 47.33 | Exact amount match one year earlier; ISS confirms |
| GTRK | 2016-06 / 1.72 | 2019-06-28 / 1.72 | GTRK IPO 2017-11-03 — impossible 2016 dividend; same amount |
| PRTK | 2013-05 / 0.18 | 2013-05-10 / 4.80 | 26× amount divergence; multiple sources confirm 4.80; CSV amount likely fragment |
| PIKK | brief said FY2018 | record 2018-09-04 = FY2017 | Brief fiscal-year off by one |
| LNZL | brief said "special" | FY2010 annual | Real special was 15219.50 RUB in 2021 |

## AGM-rejected phantoms (3 cells)

CSV row exists for a board recommendation that the AGM later rejected. No actual payment.

| Ticker | CSV cell | Reality |
|---|---|---|
| OGKB | 2024-07 / 0.058 | Fiscal 2024 = 0 (AGM rejected; dohod confirms -100%) |
| OGKB | 2025-07 / 0.06 | May 2025 AGM rejected; EGM 17.10.2025 approved 0.0598 RUB, registry 04.11.2025 |
| PHOR | 2025-07 / 201 | Board recommendation rejected by AGM 24.06.2025 |

Pipeline already drops the ISS-side phantoms via task 013 conflict entries.

## Multi-event aggregation (1 cell)

CSV combines two separate registry-close events in the same week into one cell.

| Ticker | CSV cell | Real events |
|---|---|---|
| MDMG | 2020-09 / 28.27 | 18.50 (2020-09-16, FY2019-final) + 9.80 (2020-09-18, 6m-2020 interim) |

Pipeline stores per-event — augment as TWO records.

## Pre-split nominal (1 cell)

CSV stores pre-split nominal; pipeline convention is post-split denomination.

| Ticker | CSV cell | Real | Adjustment |
|---|---|---|---|
| PLZL | 2013-11 / 26.23 | 2.623 RUB post-split | PLZL 1:10 split 2025-03-27; all pre-split records divided by 10 |

## Net-vs-gross convention divergence

CSV occasionally stores net-of-13%-tax amount, while web sources publish gross. Pipeline applies `tax_rate` constant centrally (`config.py`) → **store gross**.

Confirmed cases:
- GLTR 2018-04 — CSV 41.78 (net) vs IR 44.85 (gross). +7%, exactly 13%-tax-back.
- Possibly POLY 2019-09 — CSV 13.29 vs smart-lab 16.75 (26% diff, larger than tax alone; FX timing artifact also possible).

## USD-payer FX-mismatch (~92 cells across 8 tickers)

CSV stores RUB equivalent (converted at unknown FX cut-off); pipeline historically stored USD original. After task 016, manual_disclosure RUB augments coexist with USD ISS records; `corporate/apply.py` drops non-RUB so RUB augments win in compute.

USD-payer set: POLY, QIWI, GLTR, RAGR, OKEY, ETLN, GEMC, OBUV. Plus T (TCS Group GDR predecessor period 2020-2021).

## Redomicile predecessors (11 cells, 3 tickers)

CSV concatenates pre-redomicile and post-redomicile dividend history under the current ticker. Pipeline policy: treat redomicile as ticker change → predecessor period acknowledged as out-of-scope gap.

Affected: HEAD (4 cells 2019-2022, Cyprus HHRU predecessor), X5 (4 cells 2020-2021, Netherlands FIVE predecessor), FIXR (3 cells 2021-2024, Cyprus FIXR predecessor).

## Approximate-date augments (4 cells)

Agent confirmed amount but couldn't pinpoint registry-close day; used AGM-cycle estimate. CSV cell month differs from estimate.

| Ticker | CSV cell | Augment registry | Reason |
|---|---|---|---|
| KBTK | 2012-03 / 6.0 | 2012-05-15 | Cashstat confirms amount; precise registry not in any source |
| KBTK | 2013-03 / 5.0 | 2013-05-15 | Same — amount certain, day estimated |
| DGBZP | 2011-03 / 1.0 | 2011-06-30 | mfd.ru announcement; AGM typically June |
| MRKY | 2014-05 / 0.00014 | 2014-07-14 | Dohod registry; CSV encodes announcement date |

## End-of-month registry convention

CSV uniformly uses `YYYY-MM-31` (or last day of month) regardless of real registry day. Real registries cluster early-next-month for late-month AGMs. Gap report `regen_csv_gap_report.py` uses `MATCH_WINDOW_MONTHS = 1` to soft-match this convention.

## Currency-null records (yahoo)

Some yahoo-source records have `currency: null` in JSONLs (KRSG, MRKY, GTRK pre-2014). Pipeline treats null as RUB by default; gap report fixed to do the same.

## Source divergence patterns

- **gross vs net**: smart-lab gross, dohod sometimes net (15% withholding). 1.8-13% diff. Pipeline → gross.
- **declaration vs registry vs payment date** as cell key: CSV uses end-of-month-registry; some web sources index by declaration; some by payment. ±1 month tolerance covers.
- **investing.com currency mislabel**: BEGY page reports USD-denominated values despite RUB column header — sanity-check via CBR-rate back-multiplication.

---

## Aggregator file (gitignored) for reference

Per-cell raw findings live in `validate_with_raw/wave{1..4}_agent{1..16}.json` (16 files) with full `evidence_url` + `evidence_quote` per record. The `legacy_gap_acknowledged.json` in the same folder catalogs the 47 explicit CSV-defect acks. Both are QA-only — not loaded by production scripts.
