from __future__ import annotations

from ingest.dividends.merge import classify_bucket


def _rec(amount: float, source: str = "moex_iss") -> dict[str, object]:
    return {
        "registry_close": "2022-07-13",
        "amount": amount,
        "currency": "RUB",
        "source": source,
    }


def test_empty_existing_passes_through() -> None:
    drops, conflicts = classify_bucket([_rec(5.0)], [])
    assert drops == []
    assert len(conflicts) == 1


def test_pairwise_near_match_drops() -> None:
    existing = [_rec(4.0), _rec(5.0)]
    proposed = [_rec(4.01), _rec(5.005)]
    drops, conflicts = classify_bucket(proposed, existing)
    assert len(drops) == 2
    assert conflicts == []


def test_aqua_pattern_proposed_is_sum_of_existing() -> None:
    # existing has multi-tranche [4, 5], external feed reports SUM [9]
    existing = [_rec(4.0), _rec(5.0)]
    proposed = [_rec(9.0, source="skill_fill_tbank")]
    drops, conflicts = classify_bucket(proposed, existing)
    assert len(drops) == 1
    assert conflicts == []


def test_trnfp_pattern_existing_is_sum_of_proposed() -> None:
    # existing has 1 ISS-aggregated record, external feed gives N tranches
    existing = [_rec(7578.27)]
    proposed = [_rec(4308.81, source="skill_fill_tbank"), _rec(3269.46, source="skill_fill_tbank")]
    drops, conflicts = classify_bucket(proposed, existing)
    assert len(drops) == 2
    assert conflicts == []


def test_genuine_conflict() -> None:
    existing = [_rec(10.0)]
    proposed = [_rec(20.0, source="skill_fill_yahoo")]
    drops, conflicts = classify_bucket(proposed, existing)
    assert drops == []
    assert len(conflicts) == 1


def test_mixed_partial_match_and_conflict() -> None:
    # one proposed near-matches existing; the other doesn't and sum-check fails
    existing = [_rec(4.0)]
    proposed = [_rec(4.01), _rec(99.0, source="skill_fill_yahoo")]
    drops, conflicts = classify_bucket(proposed, existing)
    assert len(drops) == 1
    assert len(conflicts) == 1
    assert float(conflicts[0]["amount"]) == 99.0


def test_sum_check_tolerance() -> None:
    # 9.05 vs 9.0 → within 1%, drops
    existing = [_rec(4.0), _rec(5.0)]
    proposed = [_rec(9.05, source="skill_fill_tbank")]
    drops, conflicts = classify_bucket(proposed, existing, amount_rel_tol=0.01)
    assert len(drops) == 1
    assert conflicts == []


def test_sum_check_outside_tolerance_is_conflict() -> None:
    # 9.5 vs 9.0 → 5.5% > 1% → conflict
    existing = [_rec(4.0), _rec(5.0)]
    proposed = [_rec(9.5, source="skill_fill_tbank")]
    drops, conflicts = classify_bucket(proposed, existing, amount_rel_tol=0.01)
    assert drops == []
    assert len(conflicts) == 1


def test_zero_existing_sum_skips_sum_check() -> None:
    # degenerate: existing all matched, no unmatched existing, proposed
    # unmatched can't pass sum-check; sum_e == 0 → conflict
    existing = [_rec(5.0)]
    proposed = [_rec(5.01), _rec(7.0, source="skill_fill_yahoo")]
    drops, conflicts = classify_bucket(proposed, existing)
    assert len(drops) == 1
    assert len(conflicts) == 1
    assert float(conflicts[0]["amount"]) == 7.0


def test_greedy_pairwise_does_not_double_use_existing() -> None:
    # two proposed both close to single existing → only one matches,
    # other is conflict (sum check: 5+5 vs 0 unmatched existing → conflict)
    existing = [_rec(5.0)]
    proposed = [_rec(5.01), _rec(5.02)]
    drops, conflicts = classify_bucket(proposed, existing)
    assert len(drops) == 1
    assert len(conflicts) == 1
