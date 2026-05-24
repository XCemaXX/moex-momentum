# ISS splits coverage + detector findings — 2026-05-10

## Splits in the repo (after `momentum ingest splits`)

10 tickers, all on the clean `tickers.json` universe (1029 entries):

| ticker | date | before | after | type | source |
|---|---|---:|---:|---|---|
| BELU  | 2024-08-20 | 1 | 8 | bonus_issue | manual_bonus_issue |
| GEMA  | 2024-02-08 | 1 | 10 | forward | moex_iss |
| GMKN  | 2024-04-08 | 1 | 100 | forward | moex_iss |
| KOGK  | 2025-08-15 | 1 | 100 | forward | moex_iss |
| PLZL  | 2025-03-27 | 1 | 10 | forward | moex_iss |
| ROLO  | 2023-01-18 | 1 | 10 | forward | moex_iss |
| T     | 2026-04-17 | 1 | 10 | forward | moex_iss |
| TRNFP | 2024-02-21 | 1 | 100 | forward | moex_iss |
| URKZ  | 2025-08-05 | 1 | 100 | forward | moex_iss |
| VTBR  | 2024-07-15 | 5000 | 1 | reverse | moex_iss |

The spec mentioned 5 (TRNFP/GMKN/VTBR/PLZL/T) — the others (GEMA/KOGK/ROLO/URKZ) actually trade with a correct history_from via ISS and passed the `type=share` filter. This is not a bug — the spec was written before the universe was expanded beyond TQBR.

## Detector — after a full run on reuploaded prices

- **Total suspicions: 2028** (after the fix for close=0 / +inf returns).
- **Unique tickers: 498**.
- 2024-2026 — almost clean (9 / 6 / 3). Modern ISS data is clean.
- 2022-2023 — peak 183 / 180. **War + sanction shocks**. Most are real returns, not corporate actions.
- 2014-2018 — peak 61-187. Pre-MOEX-cleanup era, thinly traded names with 30-40% daily moves.

All 6 documented splits are **suppressed** via a ±1 trading-day window (VTBR 2024-07-15, GMKN 2024-04-08, TRNFP 2024-02-21, PLZL 2025-03-27, T 2026-04-17, BELU 2024-08-20).

## SBER 2022-02-24

Spec phase 7 verification: "On SBER for 2010–2026 the detector yields 0 suspicions (Sber did not split; if it does yield any — we fix it)".

**In fact it yields one**: SBER 2022-02-24, ret=-0.366, value=98 BB ₽. This is the invasion day — a real crash, not a split. "Fixed" by adding to `data/splits/_acked.json`:

```json
[{"ticker": "SBER", "date": "2022-02-24", "comment": "war shock, real return"}]
```

After the ack — 0 suspicions on SBER ✓. The same applies to ~50-100 other "large" names on the same day. The `/fill-splits` skill (phase 13) should ack them in a batch.

## Implications for phase 13

`/fill-splits` skill workload estimate:
- **~95% acked** — pump-dumps of small securities, war/sanction shocks, delisting-resumptions.
- **~5% real fills** — 50-100 splits missing in ISS in the pre-2014 era (rough estimate by the pump-dump pattern: forward `before<after` in a liquid name without a record in `splits.json`).

The skill should support batch mode: a single pass over dozens of suspicions with minimal WebFetch (e-disclosure / smart-lab).

## Known detector limitations

1. **Threshold = 0.30** — ±1bps strict inequality. A value of 0.30 passes the float boundary because of `1.30/1 - 1 ≈ 0.3000000000000001`. Not critical — a true 30% boundary is rare.
2. **Value floor = 100k₽** — cuts off penny-trades, but a security like GEMA with a small daily value on a legitimate split date may slip through. On the current 10 splits there are no problems.
3. **No ±1bd for dividends** — dividends.registry_close is matched on exact equality. T+2 settlement is not covered. If in reality the price drops on `ex_date - 1bd`, the detector flags it. Not observed on SBER/VTBR/GMKN.
4. **Inf filter via close=0 row drop** — we lose not only zero-trade artifacts, but also (theoretically) real zero-close sessions. On MOEX shares — impossible.
