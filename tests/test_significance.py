"""Block-bootstrap inference (task 024) — numpy-only, no scipy to lean on."""

from __future__ import annotations

import numpy as np

from momentum.significance import (
    analyse_variant,
    benjamini_hochberg,
    block_length,
    info_ratio,
    reality_check,
    sharpe,
    stationary_bootstrap_indices,
)


def test_bh_known_values() -> None:
    # Classic BH example: p sorted, q_i = p_i * m / i with monotone enforcement.
    p = [0.01, 0.02, 0.03, 0.04, 0.05]
    q = benjamini_hochberg(p)
    assert np.allclose(q, [0.05, 0.05, 0.05, 0.05, 0.05])


def test_bh_preserves_input_order() -> None:
    q = benjamini_hochberg([0.04, 0.01, 0.03])
    # smallest raw p (index 1) must get the smallest q
    assert q[1] == min(q)


def test_bh_monotone_and_bounded() -> None:
    rng = np.random.default_rng(0)
    p = rng.random(50).tolist()
    q = benjamini_hochberg(p)
    assert all(0.0 <= v <= 1.0 for v in q)
    order = np.argsort(p)
    ranked_q = np.asarray(q)[order]
    assert np.all(np.diff(ranked_q) >= -1e-12)  # non-decreasing in p-order


def test_bootstrap_indices_shape_and_range() -> None:
    rng = np.random.default_rng(1)
    idx = stationary_bootstrap_indices(40, 100, 5, rng)
    assert idx.shape == (100, 40)
    assert idx.min() >= 0 and idx.max() < 40


def test_block_length_grows_sublinearly() -> None:
    assert block_length(1) == 1
    assert block_length(160) == 5  # round(160**(1/3)) = 5
    assert block_length(1000) == 10


def test_sharpe_and_ir_signs() -> None:
    r = np.full(120, 0.01)  # constant positive → infinite-ish sharpe, but std=0 guard
    assert np.isnan(sharpe(r))
    rng = np.random.default_rng(2)
    pos = rng.normal(0.01, 0.04, 240)
    assert sharpe(pos) > 0
    d = np.full(120, 0.005)
    assert np.isnan(info_ratio(d))  # zero tracking error


def test_zero_active_is_not_significant() -> None:
    rng = np.random.default_rng(3)
    base = rng.normal(0.01, 0.05, 160)
    idx = stationary_bootstrap_indices(160, 2000, 5, rng)
    res = analyse_variant("same", base.copy(), base, idx)
    assert res.ann_active == 0.0
    assert res.twr == 1.0
    assert res.p_mean == 1.0  # |0| >= |0| holds for every resample


def test_strong_edge_is_flagged_significant() -> None:
    rng = np.random.default_rng(4)
    base = rng.normal(0.0, 0.03, 200)
    variant = base + 0.02  # +2%/mo constant edge, zero added noise
    idx = stationary_bootstrap_indices(200, 5000, 6, rng)
    res = analyse_variant("edge", variant, base, idx)
    assert res.ann_active > 0.2
    assert res.p_mean < 0.05
    assert res.ci_lo > 0  # CI excludes zero


def test_reality_check_in_unit_interval_and_detects_winner() -> None:
    rng = np.random.default_rng(5)
    n = 200
    idx = stationary_bootstrap_indices(n, 3000, 6, rng)
    # All-noise active matrix → large RC p (no real winner).
    noise = rng.normal(0.0, 0.03, (n, 8))
    p_noise = reality_check(noise, idx)
    assert 0.0 <= p_noise <= 1.0
    assert p_noise > 0.10
    # One column carries a strong constant edge → small RC p.
    winner = noise.copy()
    winner[:, 3] += 0.02
    p_win = reality_check(winner, idx)
    assert p_win < p_noise
