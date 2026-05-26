"""Block-bootstrap inference for active returns — numpy only (task 024).

Monthly strategy returns are autocorrelated, non-normal and heteroskedastic, so a
plain t-test is invalid; scipy/statsmodels are also out of the stack. We use the
stationary bootstrap (Politis & Romano 1994): resample geometric-length blocks so
serial dependence survives. Reported per variant: percentile CI and a recentered
bootstrap p-value. Many variants vs one baseline → Benjamini-Hochberg FDR; the
data-snooping guard is White's Reality Check (2000) on the max statistic.

All p-values are two-sided unless noted. Returns assumed monthly; annualisation
uses ×12 (mean) and ×√12 (vol).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.intp]

_MONTHS = 12
_SQRT_MONTHS = float(np.sqrt(_MONTHS))


def block_length(n: int) -> int:
    """Expected stationary-block length. n**(1/3) is the standard order; small
    samples floor at 1."""
    return max(1, int(round(n ** (1.0 / 3.0))))


def stationary_bootstrap_indices(
    n: int, n_boot: int, expected_block: int, rng: np.random.Generator
) -> IntArray:
    """(n_boot, n) resample indices. Each position either starts a new block at a
    random point (prob 1/expected_block) or continues the previous one circularly."""
    p = 1.0 / expected_block
    idx = np.empty((n_boot, n), dtype=np.intp)
    starts = rng.integers(0, n, size=(n_boot, n))
    new_block = rng.random((n_boot, n)) < p
    new_block[:, 0] = True
    cur = np.zeros(n_boot, dtype=np.intp)
    for j in range(n):
        cur = np.where(new_block[:, j], starts[:, j], (cur + 1) % n)
        idx[:, j] = cur
    return idx


def annualised_mean(d: FloatArray) -> float:
    return float(np.mean(d)) * _MONTHS


def tracking_error(d: FloatArray) -> float:
    return float(np.std(d, ddof=1)) * _SQRT_MONTHS


def info_ratio(d: FloatArray) -> float:
    te = tracking_error(d)
    return annualised_mean(d) / te if te > 0 else float("nan")


def sharpe(r: FloatArray) -> float:
    sd = float(np.std(r, ddof=1))
    return float(np.mean(r)) / sd * _SQRT_MONTHS if sd > 0 else float("nan")


@dataclass
class VariantResult:
    name: str
    n: int
    ann_active: float  # annualised mean active return
    tracking_error: float
    info_ratio: float
    twr: float  # terminal-wealth ratio, variant / baseline
    sharpe_variant: float
    sharpe_base: float
    sharpe_diff: float
    p_mean: float  # bootstrap p, H0: mean active = 0
    ci_lo: float  # 95% CI on annualised active return
    ci_hi: float


def _percentile_ci(samples: FloatArray, scale: float) -> tuple[float, float]:
    lo, hi = np.percentile(samples, [2.5, 97.5])
    return float(lo) * scale, float(hi) * scale


def analyse_variant(
    name: str,
    r_variant: FloatArray,
    r_base: FloatArray,
    idx: IntArray,
) -> VariantResult:
    """Full active-return analysis of one variant against the baseline, using a
    shared bootstrap index `idx` (so cross-correlation is preserved)."""
    d = r_variant - r_base
    n = d.shape[0]

    boot_mean = d[idx].mean(axis=1)
    obs_mean = float(np.mean(d))
    centered = boot_mean - obs_mean
    p_mean = float(np.mean(np.abs(centered) >= abs(obs_mean)))
    ci_lo, ci_hi = _percentile_ci(boot_mean, _MONTHS)

    sv, sb = sharpe(r_variant), sharpe(r_base)
    obs_sdiff = sv - sb

    twr = float(np.prod(1.0 + r_variant) / np.prod(1.0 + r_base))
    return VariantResult(
        name=name,
        n=n,
        ann_active=annualised_mean(d),
        tracking_error=tracking_error(d),
        info_ratio=info_ratio(d),
        twr=twr,
        sharpe_variant=sv,
        sharpe_base=sb,
        sharpe_diff=obs_sdiff,
        p_mean=p_mean,
        ci_lo=ci_lo,
        ci_hi=ci_hi,
    )


def benjamini_hochberg(pvals: list[float]) -> list[float]:
    """BH-adjusted q-values (FDR control), order-preserving with the input."""
    p = np.asarray(pvals, dtype=np.float64)
    m = p.shape[0]
    if m == 0:
        return []
    order = np.argsort(p)
    ranked = p[order]
    q = ranked * m / np.arange(1, m + 1)
    q = np.minimum.accumulate(q[::-1])[::-1]
    q = np.clip(q, 0.0, 1.0)
    out = np.empty(m, dtype=np.float64)
    out[order] = q
    return [float(v) for v in out]


def reality_check(active: FloatArray, idx: IntArray) -> float:
    """White's Reality Check p-value for H0: the best of K variants does not beat
    the baseline, accounting for the search. `active` is (n, K) of active returns;
    statistic V = max_k √n·mean(d_k); bootstrap recenters each column."""
    n, k = active.shape
    root_n = float(np.sqrt(n))
    dbar = active.mean(axis=0)
    obs = root_n * float(dbar.max())
    nb = idx.shape[0]
    stat = np.full(nb, -np.inf)
    for col in range(k):
        boot_mean = active[:, col][idx].mean(axis=1)
        stat = np.maximum(stat, root_n * (boot_mean - dbar[col]))
    return float(np.mean(stat >= obs))


__all__ = [
    "FloatArray",
    "IntArray",
    "VariantResult",
    "analyse_variant",
    "annualised_mean",
    "benjamini_hochberg",
    "block_length",
    "info_ratio",
    "reality_check",
    "sharpe",
    "stationary_bootstrap_indices",
    "tracking_error",
]
