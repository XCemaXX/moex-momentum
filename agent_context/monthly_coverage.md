# Monthly computed coverage — 2026-05-11

After `momentum compute monthly` (full):
- **1025 tickers** with records (universe = 1029, minus 4 without prices).
- **Non-RUB dividends dropped: 9** (8 POLY 2015-2018, 1 RUAL 2022-10). Each is a WARN in the log. FX conversion is out of plan scope; the affected tickers are either both delisted (POLY) or practically illiquid for momentum.

## Sanity-checks on real data

**VTBR consolidation 2024-07-15 (5000:1)**
- close_adj 2024-05 = 98.83 (raw ~0.01977 × 5000)
- close_adj 2024-06 = 105.70 (raw ~0.02114 × 5000)
- close_adj 2024-07-31 = 97.82 (post-split, raw)
- The `price_return` returns are smooth through the split: -15%/+7%/-7.5% — no ±1000% spikes.

**TRNFP forward 1:100 2024-02-21**
- Adjusted closes pre-split: × 0.01 → ~1200-1400 RUB scale, same as post-split.

**BELU bonus_issue 1:8 2024-08-20**
- Adjusted closes pre-split: × 0.125 → ~600-700 RUB scale.

**Dividend sample — selected rows**
| ticker | month | div_return | nominal | notes |
|---|---|---:|---:|---|
| SBER | 2025-07 | +9.27% | 34.84 ₽ | close_pre_ex ~316 |
| VTBR | 2025-07 | +23.81% | 25.79 ₽ | post-cons scale |
| TRNFP | 2025-07 | +11.51% | massive div |
| BELU | 2025-06 | +4.64% | ~20 ₽ adj |

All within expectations (12-25% annual × 1 payout).

## Known limitations

1. **Non-RUB dividends silently dropped** — POLY divs before delisting are not counted. Since POLY was delisted on MOEX in 2023 and the ticker leaves the universe, losing ~9 events does not affect the current backtest.
2. **No `close_pre_ex` if the ex-date is earlier than the first price** — WARN, skip. Not observed on real data.
3. **`close_pre_ex_adj` = strictly the previous trading day**, not `ex_date - 1bd`. If the pricing history has a gap (weekends, holiday) — the last actual trading day is taken, which is correct for T+0 settlement.
4. **Zero-volume monthly close** — if the last day of the month has `close=0` (pre-2010 artifact), it is filtered out in apply_splits, and monthly takes the **previous** trading day. This is correct — otherwise the ratio turns into NaN/inf.

## Phase 9 readiness

For each ticker `data/computed/monthly/{TICKER}.jsonl` with columns:
`month, month_end_date, close_adj, price_return, div_return, total_return`.

This is exactly the "long-format DataFrame: `[ticker, year_month, close_adj, total_return]`" from the plan. `price_return` + `div_return` are stored for debugging and for a possible alternative formula (e.g. without dividends).
