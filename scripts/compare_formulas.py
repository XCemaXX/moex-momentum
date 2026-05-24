"""Statistical compare of two momentum signals: `simple` vs `curve_fit`.

One-shot research script (NOT part of the production CLI). Reads the on-disk
backtest outputs only; recomputes nothing about the strategy itself.

  simple    = r(12-1) / sigma(12)
  curve_fit = (0.9*r(12-1) + 0.1*r(6-1)) / sigma(12)   (current production default)

Inputs (read-only):
  data/momentum/{simple,curve_fit}/q_values.csv       NAV curves: month,Q1..Q4,MCFTRR
  data/momentum/{simple,curve_fit}/holdings/YYYY-MM.json   equal-weight quartile members

Stats stack note: scipy is NOT in the locked stack, so the parametric paired
t-test / Wilcoxon are replaced by a sign-flip permutation test, and Spearman rho
comes from pandas .corr(method="spearman"). Bootstrap uses numpy only. All
randomness is seeded (numpy seed=0) so the script is deterministic on re-run.

Run: .venv/bin/python scripts/compare_formulas.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SIGNALS = ("simple", "curve_fit")
QUARTILES = ("Q1", "Q2", "Q3", "Q4")

MONTHS_PER_YEAR = 12
SEED = 0
N_PERM = 10_000
N_BOOT = 10_000
BLOCK = 12  # block bootstrap block length (months)


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def load_navs(signal: str) -> pd.DataFrame:
    """NAV panel indexed by month (str YYYY-MM), columns Q1..Q4 + MCFTRR."""
    df = pd.read_csv(ROOT / "data" / "momentum" / signal / "q_values.csv")
    return df.set_index("month").sort_index()


def load_holdings(signal: str) -> dict[str, dict[str, list[str]]]:
    """month -> {Q1:[...], ...}. Keyed by the month the holdings were chosen at."""
    out: dict[str, dict[str, list[str]]] = {}
    hdir = ROOT / "data" / "momentum" / signal / "holdings"
    for f in sorted(hdir.glob("*.json")):
        out[f.stem] = json.loads(f.read_text())
    return out


# --------------------------------------------------------------------------- #
# Per-curve performance metrics
# --------------------------------------------------------------------------- #
def cagr(nav: pd.Series) -> float:
    n = len(nav) - 1  # number of monthly steps
    return float((nav.iloc[-1] / nav.iloc[0]) ** (MONTHS_PER_YEAR / n) - 1)


def sharpe(nav: pd.Series) -> float:
    """Annualized Sharpe from monthly log-returns, rf=0."""
    logret = np.log(nav / nav.shift(1)).dropna()
    sd = logret.std(ddof=1)
    if sd == 0:
        return float("nan")
    return float(logret.mean() / sd * np.sqrt(MONTHS_PER_YEAR))


def max_drawdown(nav: pd.Series) -> float:
    """Most-negative point of NAV/cummax - 1 (returned as a negative number)."""
    return float((nav / nav.cummax() - 1).min())


def calmar(c: float, mdd: float) -> float:
    if mdd == 0:
        return float("nan")
    return float(c / abs(mdd))


def long_short_nav(navs: pd.DataFrame) -> pd.Series:
    """Q1-Q4 long-short proxy = NAV_Q1 / NAV_Q4 (both start at 1.0)."""
    return navs["Q1"] / navs["Q4"]


# --------------------------------------------------------------------------- #
# Turnover
# --------------------------------------------------------------------------- #
def annual_turnover(
    holdings: dict[str, dict[str, list[str]]], quartile: str, n_years: float
) -> float:
    """Sum over rebalances of 0.5*sum_i|dw_i|, divided by years.

    Equal weight 1/N on that month's members. Compared against the previous
    month's weights for the same quartile over the union of ticker sets.
    Entering from an empty book = turnover 1.0. The first month has no prior
    book, so it contributes 1.0 (full initial buy)."""
    months = sorted(holdings)
    prev: dict[str, float] = {}
    total = 0.0
    for m in months:
        members = holdings[m][quartile]
        cur = {t: 1.0 / len(members) for t in members} if members else {}
        tickers = set(prev) | set(cur)
        total += 0.5 * sum(abs(cur.get(t, 0.0) - prev.get(t, 0.0)) for t in tickers)
        prev = cur
    return total / n_years


# --------------------------------------------------------------------------- #
# Cross-signal: monotonicity, bootstrap, permutation
# --------------------------------------------------------------------------- #
def spearman_monotonicity(navs: pd.DataFrame) -> float:
    """Spearman rho between quartile ordinal (Q1=1..Q4=4) and the quartile's
    mean monthly return.

    Convention: ordinal increases Q1->Q4 (1,2,3,4). If Q1 has the highest mean
    return and the ranking decreases monotonically, rho = -1.0 (perfect
    monotone decreasing). rho near -1 confirms "Q1 best, monotone"; values near
    0 mean the quartiles are not monotonically ordered by return."""
    rets = navs[list(QUARTILES)].pct_change().dropna()
    mean_ret = rets.mean()  # index Q1..Q4
    ordinal = pd.Series([1, 2, 3, 4], index=list(QUARTILES), dtype=float)
    # DataFrame.corr(spearman) uses pandas' own rank impl (no scipy); Series.corr
    # would delegate to scipy.stats.spearmanr, which is not in the locked stack.
    df = pd.DataFrame({"ordinal": ordinal, "mean_ret": mean_ret})
    return float(df.corr(method="spearman").loc["ordinal", "mean_ret"])


def q1_monthly_returns(navs: pd.DataFrame) -> pd.Series:
    return navs["Q1"].pct_change().dropna()


def permutation_pvalue(diff: np.ndarray, rng: np.random.Generator) -> float:
    """Two-sided sign-flip permutation test on paired differences.

    H0: the paired differences are symmetric about 0. Flip each difference's
    sign independently; p = fraction of permuted |mean| >= observed |mean|."""
    obs = abs(float(diff.mean()))
    signs = rng.choice([-1.0, 1.0], size=(N_PERM, diff.size))
    perm_means = np.abs((signs * diff).mean(axis=1))
    return float((perm_means >= obs).mean())


def block_bootstrap_ci(
    ret_simple: pd.Series, ret_cf: pd.Series, rng: np.random.Generator
) -> tuple[float, float, float]:
    """95% CI on (NAV_simple / NAV_curve_fit - 1) for Q1.

    Resample months in non-overlapping blocks of length BLOCK; the SAME block
    indices apply to both signals so the pairing is preserved. Compound each
    resampled return series to a terminal NAV, take the ratio - 1.
    Returns (point_estimate, lo_2.5%, hi_97.5%)."""
    rs = ret_simple.to_numpy()
    rc = ret_cf.to_numpy()
    n = rs.size
    n_blocks = int(np.ceil(n / BLOCK))
    max_start = n - BLOCK  # inclusive

    point = float(np.prod(1.0 + rs) / np.prod(1.0 + rc) - 1.0)

    stats = np.empty(N_BOOT)
    for b in range(N_BOOT):
        starts = rng.integers(0, max_start + 1, size=n_blocks)
        idx = np.concatenate([np.arange(s, s + BLOCK) for s in starts])[:n]
        nav_s = np.prod(1.0 + rs[idx])
        nav_c = np.prod(1.0 + rc[idx])
        stats[b] = nav_s / nav_c - 1.0
    lo, hi = np.percentile(stats, [2.5, 97.5])
    return point, float(lo), float(hi)


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def per_signal_metrics(navs: pd.DataFrame, holdings: dict[str, dict[str, list[str]]]) -> dict:
    n_months = len(navs) - 1
    n_years = n_months / MONTHS_PER_YEAR

    cols: dict[str, dict[str, float]] = {}
    curves = {q: navs[q] for q in QUARTILES}
    curves["Q1-Q4"] = long_short_nav(navs)

    for label, nav in curves.items():
        c = cagr(nav)
        mdd = max_drawdown(nav)
        m = {"CAGR": c, "Sharpe": sharpe(nav), "MaxDD": mdd, "Calmar": calmar(c, mdd)}
        if label in QUARTILES:
            m["AnnTurnover"] = annual_turnover(holdings, label, n_years)
        else:
            m["AnnTurnover"] = float("nan")  # long-short turnover not defined here
        cols[label] = m

    # Hit rate: Q1 monthly return > MCFTRR monthly return.
    q1_ret = navs["Q1"].pct_change().dropna()
    bench_ret = navs["MCFTRR"].pct_change().dropna()
    hit = float((q1_ret > bench_ret).mean())

    return {
        "metrics": cols,
        "hit_rate_q1": hit,
        "spearman": spearman_monotonicity(navs),
        "n_months": n_months,
    }


def fmt(x: float, pct: bool = False) -> str:
    if np.isnan(x):
        return "    n/a"
    return f"{x * 100:7.2f}%" if pct else f"{x:7.3f}"


def main() -> None:
    rng = np.random.default_rng(SEED)

    navs = {s: load_navs(s) for s in SIGNALS}
    holds = {s: load_holdings(s) for s in SIGNALS}

    # Alignment sanity: both panels must share the same month index.
    if not navs["simple"].index.equals(navs["curve_fit"].index):
        raise ValueError("simple and curve_fit q_values have different month indexes")
    span = f"{navs['simple'].index[0]} -> {navs['simple'].index[-1]}"

    res = {s: per_signal_metrics(navs[s], holds[s]) for s in SIGNALS}

    # ---- per-quartile metric table ----
    metric_rows = ("CAGR", "Sharpe", "MaxDD", "Calmar", "AnnTurnover")
    pct_rows = {"CAGR", "MaxDD"}
    print("\n=== Formula comparison: simple vs curve_fit ===")
    print(f"Panel: {span}  ({res['simple']['n_months']} monthly returns)\n")

    for label in (*QUARTILES, "Q1-Q4"):
        print(f"--- {label} ---")
        print(f"{'metric':<12} {'simple':>10} {'curve_fit':>10}")
        for mk in metric_rows:
            sv = res["simple"]["metrics"][label][mk]
            cv = res["curve_fit"]["metrics"][label][mk]
            p = mk in pct_rows
            print(f"{mk:<12} {fmt(sv, p):>10} {fmt(cv, p):>10}")
        print()

    print("--- Q1 extras ---")
    print(
        f"{'hit-rate vs MCFTRR':<22} simple={fmt(res['simple']['hit_rate_q1'], True).strip()}"
        f"  curve_fit={fmt(res['curve_fit']['hit_rate_q1'], True).strip()}"
    )
    print(
        f"{'Q1 terminal NAV':<22} simple={navs['simple']['Q1'].iloc[-1]:.3f}"
        f"  curve_fit={navs['curve_fit']['Q1'].iloc[-1]:.3f}"
    )
    print(f"{'MCFTRR terminal NAV':<22} {navs['simple']['MCFTRR'].iloc[-1]:.3f}\n")

    # ---- Spearman monotonicity ----
    print("--- Spearman rho (quartile ordinal 1..4 vs mean monthly return) ---")
    print("convention: rho=-1 => perfectly monotone decreasing (Q1 best); ~0 => not monotone")
    for s in SIGNALS:
        print(f"  {s:<10} rho = {res[s]['spearman']:+.4f}")
    print()

    # ---- Cross-signal Q1 statistics ----
    rs = q1_monthly_returns(navs["simple"])
    rc = q1_monthly_returns(navs["curve_fit"])
    common = rs.index.intersection(rc.index)
    rs, rc = rs.loc[common], rc.loc[common]

    point, lo, hi = block_bootstrap_ci(rs, rc, rng)
    print("--- Block bootstrap 95% CI on (NAV_simple / NAV_curve_fit - 1), Q1 ---")
    print(f"  block length = {BLOCK} months, resamples = {N_BOOT}, seed = {SEED}")
    print(f"  point estimate = {point:+.4f}  ({point * 100:+.2f}%)")
    print(f"  95% CI = [{lo:+.4f}, {hi:+.4f}]")
    inside = lo <= 0.0 <= hi
    print(
        f"  0.0 {'IS' if inside else 'is NOT'} inside CI -> Q1 difference "
        f"{'NOT significant' if inside else 'significant'}\n"
    )

    diff = (rs - rc).to_numpy()
    pval = permutation_pvalue(diff, rng)
    print("--- Paired sign-flip permutation test on monthly Q1 returns (simple - curve_fit) ---")
    print(f"  permutations = {N_PERM}, seed = {SEED}")
    print(f"  observed mean diff = {diff.mean():+.6f} per month")
    print(
        f"  two-sided p-value = {pval:.4f}  "
        f"({'reject' if pval < 0.05 else 'fail to reject'} H0 at 5%)\n"
    )


if __name__ == "__main__":
    main()
