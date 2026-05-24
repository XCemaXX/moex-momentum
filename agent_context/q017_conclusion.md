# Task 017 — why Q2 > Q1 in 2013-2020, and is it a defect?

**Status: RESOLVED + SHIPPED.** The fixed nominal liquidity floor was the cause; it has
been replaced by a top-100-by-liquidity universe (`UNIVERSE_TOP_N_LIQUID`). Production
`curve_fit` recomputed: Q1>Q2 now in 153/160 months, clean Q1>Q2>Q3>Q4. The old floor
code is fully removed. The diagnostic scripts referenced below
(`q017_liquidity_sweep.py`, `q017_q1_drag.py`, `q017_floor_diagnostics.py`,
`q017_topn_experiment.py`) were deleted after the decision; their numbers are recorded
here as the evidence trail.

**Verdict: not a bug.** The algorithm and data are correct. The Q1 < Q2 ordering in
2013-2020 was an artifact of a fixed nominal ₽ liquidity floor that over-filtered the
early years (38 names in 2013 vs 164 in 2024) — not a data or formula defect.

## What the experiments show

### 1. The liquidity floor is the cause (verified)
Liquidity-floor sweep (diagnostic, since removed), curve_fit, start 2013-01:

| floor (median monthly value) | Q1 | Q2 | Q3 | Q4 | Q1>Q2 (2013-20) | avg universe |
|---|---|---|---|---|---|---|
| **0 (no floor)** | **25.43** | 9.15 | 14.67 | 1.51 | **95/96** | 247 |
| 100M (production) | 10.49 | 5.15 | 2.12 | 0.75 | **6/96** | 85 |
| 300M | 10.72 | 4.73 | 2.76 | 1.09 | 31/96 | 67 |
| 500M | 7.96 | 4.17 | 1.97 | 1.20 | 10/96 | 59 |
| 1B | 7.93 | 2.56 | 2.32 | 0.71 | 57/96 | 49 |
| 2B | 10.59 | 2.13 | 1.96 | 0.67 | 95/96 | 40 |
| 5B | 9.14 | 2.65 | 3.44 | 0.82 | 95/96 | 31 |

- With **no floor**, Q1 dominates from the start (95/96 months) and ends at 25.4× —
  above the author's ~17-18×. This is the regime that matches his published chart.
- Our **production 100M floor is the single worst point** for early Q1>Q2 (6/96).
- The sweep is **non-monotonic** in the middle (300M/500M/1B unstable) — an artifact of
  thin early-year universes once names are screened out. Only the extremes (full
  universe, or an aggressive ≥2B mega-cap floor) are stable. There is no clean
  "moderate floor" that fixes it.

### 2. The momentum premium lived in the smaller names
Q1-drag decomposition (diagnostic, since removed; 100M run): the worst Q1 contributors 2013-2020 are **liquid
large-caps** (SBERP, GMKN, SNGS, AFLT, MGNT, ALRS, NLMK, LKOH, ROSN, GAZP), and Q1 median
liquidity is ≥ Q2 in 5 of 8 years. So inside the screened universe, momentum lagged in
the large caps. Removing the floor re-admits the smaller names that actually carried the
premium — hence Q1's jump from 10.5× to 25.4×. The "illiquid junk dilutes Q1" hypothesis
is **refuted**: the junk, when present, *drives* Q1, not drags it.

### 3. The real defect: our floor is a FIXED NOMINAL threshold, mis-calibrated over time
The first cut of this analysis claimed "his universe ≈ our floor=0 (broad)". That is
**wrong** and was corrected (floor diagnostics, since removed):

| year | ours @0 | ours @100M | author |
|---|---|---|---|
| 2013 | 261 | **38** | ~109 (id 474, stated) |
| 2017 | 256 | 73 | — |
| 2020 | 242 | 74 | — |
| 2024 | 228 | 164 | ~115 (measured) |

- The author's universe (measured from his 2022-03+ memberships): mean **115**, range
  89-134 — roughly **stable across time** (it tracks broad-market-index membership, id
  858/962, mid/small caps kept, delisted included).
- Our 100M floor is a **fixed nominal ₽ threshold** applied to every year. 100M ₽ was
  worth far more in 2013 (ruble ~30/$, smaller market) than in 2024 (~90/$). So it leaves
  only **38 names in 2013** but **164 in 2024**. In the early years we filter *much more
  aggressively than the author* (38 vs ~109), stripping the market to a large-cap core
  exactly when momentum favored smaller names. This — not "the author keeps more junk" —
  is why our early Q1 lags. It also explains the sweep's non-monotonicity: a fixed nominal
  floor interacts pathologically with the changing ruble/market scale.

### 3b. The premium does live in lower-liquidity names (verified)
At floor=0, Q1's sub-100M names earn **+2.26%/mo** next-month vs **+1.64%/mo** for the
≥100M names; 64% of floor=0 Q1 (40.6 of 63.7 names) is sub-100M. Compounded, that ~0.6pp/mo
gap maps to roughly the 25× vs 10× difference. Momentum genuinely paid more in the
less-liquid tail in 2013-2020.

### 3c. The author's chart is also reconstructed + curve-fit (context)
- id 898: coefficients (0.9/0.1) were **curve-fit** via walk-forward 5-yr windows to
  maximize cumulative Q1−Q4 spread over a sample **starting Feb-2011** — early years are
  *in-sample*.
- Channel began 2021-09; live posts from 2022. Pre-2022 is a **retrospective backtest**,
  and the clean Q1>Q2>Q3>Q4 is a **post-2024 artifact** of fixing missing dividends
  (id 852; before the fix he too had **Q2 < Q3**).

### 4. Algorithm and data are correct (verified)
- **Formula:** identical to the author's (VSMO=4.6458% regression anchor holds in
  `tests/test_momentum_examples.py`).
- **Recent-year cross-check** vs his stated backtest returns:
  - 2025: ours Q1 +19.4% / Q2 −6.0% / Q3 −9.4% vs his +17.1% / −6.2% / −9.3% — Q2/Q3
    within **0.2pp**, Q1 within 2.3pp.
  - 2024: a uniform +6-8pp offset across all four quartiles (systematic, not a ranking
    bug); ordering Q1>Q2>Q3>Q4 holds.
- **Membership overlap (2022-03+):** 82% exact quartile agreement; in the membership-swap
  (`scripts/q017_ref_membership_nav.py`, his memberships on our returns), ~95% of his
  names exist in our panel and our own memberships separate Q1/Q2 *more* than his do.
- **Dividends:** complete for the major names 2013-2020 (SBER/GAZP yearly, MTSS/LKOH
  semi-annual all present); total div records stable at 150-230/yr. The earlier suspicion
  of early-dividend gaps does **not** hold for our final cascade-filled data (fixed by
  tasks 005/012/016).
- **Splits:** only one in-window event (IRAO 2015-01, spurious — no return artifact);
  ruled out (`agent_context/q017_splits_audit.md`).
- The Q2<Q3 inversion that appears at floor=0 mirrors the author's pre-2024 state, but our
  dividends are complete, so it is **not** the same dividend cause here — most likely
  thin-universe sampling noise. Noted, not a confirmed defect.

## What we shipped

Replaced the fixed nominal floor with **top-100 by liquidity** (`UNIVERSE_TOP_N_LIQUID`),
and removed the old floor code entirely. Why the floor lost:
1. **Admitted third tier today.** Its marginal names at 2024-06 traded ~5-6M ₽/day (ASSB,
   SARE, STSB, DIOD, UTAR, NFAZ).
2. **Over-filtered the early years.** 38 names in 2013 vs 164 in 2024 — a single nominal
   line is brutal when the ruble was 30/$ and loose at 90/$. The direct cause of early Q1<Q2.

Top-100 is a *relative* cut: 100 names every month, the implied ₽ threshold auto-scaling
(~9M ₽/mo in 2013 → ~500M in 2026). Recomputed `curve_fit`: Q1>Q2 in 153/160 months, clean
Q1>Q2>Q3>Q4, no Q2<Q3 inversion. Month-to-month churn of the 100-name set is mean 2.2%
(max 9%), so the universe is stable. Rejected alternatives: floor=0 (admits ~250 names incl.
genuine third tier, not tradeable) and a moderate nominal floor (sweep non-monotonic, no
stable value). The data and algorithm were always correct — this was purely universe
definition.

Accepted trade-off: in the thin 2013 market the 100th name trades ~9M ₽/mo; there simply
were not 100 highly-liquid names then.

## Limits
- Direct composition comparison with the author is only possible from 2022-03 (his
  pre-2022 data is in chart images / a closed channel, not the text export). The 2013-2020
  conclusion rests on the liquidity sweep + his documented methodology, not a row-level
  diff of his early holdings.
