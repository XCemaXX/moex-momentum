"""Quartile-transition analysis (task 001) — flow counts and sticky tenure."""

from __future__ import annotations

from momentum.transitions import sticky_tickers, transition_flows, transition_windows

# A new ticker (F) enters, one (E) drops out, one (B) walks Q1→Q2→Q3.
HOLDINGS = {
    "2020-01": {"Q1": ["A", "B"], "Q2": ["C"], "Q3": ["D"], "Q4": ["E"]},
    "2020-02": {"Q1": ["A"], "Q2": ["B", "C"], "Q3": ["D"], "Q4": []},
    "2020-03": {"Q1": ["A", "F"], "Q2": ["C"], "Q3": ["B", "D"], "Q4": []},
}


def test_transition_flows_counts() -> None:
    f = transition_flows(HOLDINGS)
    assert f[("Q1", "Q1")] == 2  # A holds Q1 across both pairs
    assert f[("Q1", "Q2")] == 1  # B leaves Q1
    assert f[("Q2", "Q2")] == 2  # C holds Q2
    assert f[("Q2", "Q3")] == 1  # B Q2→Q3
    assert f[("Q4", "Dropped")] == 1  # E leaves the universe
    assert f[("New", "Q1")] == 1  # F enters into Q1


def test_transition_flows_empty_history() -> None:
    assert transition_flows({}) == {}
    assert transition_flows({"2020-01": {"Q1": ["A"]}}) == {}  # no pair


def test_sticky_longest_run_per_quartile() -> None:
    s = sticky_tickers(HOLDINGS, top_n=10)
    a = s["Q1"][0]
    assert (a.ticker, a.length, a.start, a.end) == ("A", 3, "2020-01", "2020-03")
    assert s["Q2"][0].ticker == "C" and s["Q2"][0].length == 3
    assert s["Q3"][0].ticker == "D" and s["Q3"][0].length == 3
    assert [r.ticker for r in s["Q4"]] == ["E"]


def test_sticky_tie_break_prefers_recent_end() -> None:
    # Q1 has A(len 3) then F and B tied at len 1; F ends later → ranks above B.
    assert [r.ticker for r in sticky_tickers(HOLDINGS)["Q1"]] == ["A", "F", "B"]


def test_sticky_run_breaks_on_gap_not_merged() -> None:
    # G leaves Q1 then returns: two runs of 1, never a single run of 2.
    holdings = {
        "2020-01": {"Q1": ["G"], "Q2": [], "Q3": [], "Q4": []},
        "2020-02": {"Q1": [], "Q2": ["G"], "Q3": [], "Q4": []},
        "2020-03": {"Q1": ["G"], "Q2": [], "Q3": [], "Q4": []},
    }
    runs = sticky_tickers(holdings)["Q1"]
    assert len(runs) == 1
    assert runs[0].ticker == "G" and runs[0].length == 1


def test_transition_windows_boundary() -> None:
    # Strict y*12 < len: at exactly a window's length it folds into "all"
    # (identical data, no redundant button). 12 months → only "all".
    m12 = [f"2020-{i:02d}" for i in range(1, 13)]
    assert [w for w, _ in transition_windows(m12)] == ["all"]
    # 13 months → "1y" (trailing 12) appears alongside "all".
    assert [w for w, _ in transition_windows([*m12, "2021-01"])] == ["1y", "all"]


def test_sticky_top_n_caps_list() -> None:
    holdings = {"2020-01": {"Q1": [f"T{i}" for i in range(20)], "Q2": [], "Q3": [], "Q4": []}}
    assert len(sticky_tickers(holdings, top_n=10)["Q1"]) == 10
