"""Quartile-transition analysis (task 001), computed from per-month holdings.

Two products, both pure functions over the holdings dict the site already loads:

  - transition_flows: aggregate Qᵢ(t) → Qⱼ(t+1) counts over all consecutive month
    pairs, plus New→Qⱼ (entered the universe) and Qᵢ→Dropped (left it). The
    diagonal Qᵢ→Qᵢ is the stickiness mass — what the Sankey visualises.
  - sticky_tickers: per quartile, the names with the longest unbroken tenure in
    that quartile (the "stickiest"). Tenure, not the persistence factor P: it is
    the literal "stays longest in one quartile" metric and needs no signal.

Adjacency is positional over the sorted months: holdings are assumed
calendar-contiguous (true by construction — every month is computed). A gap
would bridge flows and tenure across it.
"""

from __future__ import annotations

from dataclasses import dataclass

Holdings = dict[str, dict[str, list[str]]]
Q_LABELS = ("Q1", "Q2", "Q3", "Q4")
NEW = "New"
DROPPED = "Dropped"
# Trailing windows offered by the period selector (years); "all" is appended.
WINDOW_YEARS = (1, 3, 5, 10)


def transition_windows(months: list[str]) -> list[tuple[str, list[str]]]:
    """[(label, window_months)] for trailing 1y/3y/5y/10y that fit, plus 'all'.

    Shared by the Sankey and the sticky list so one period control drives both.
    """
    out = [(f"{y}y", months[-y * 12 :]) for y in WINDOW_YEARS if y * 12 < len(months)]
    out.append(("all", list(months)))
    return out


@dataclass(frozen=True)
class StickyRun:
    ticker: str
    quartile: str
    length: int  # consecutive months held in this quartile
    start: str  # first month of the run (YYYY-MM)
    end: str  # last month of the run


def _ticker_quartile(month_holdings: dict[str, list[str]]) -> dict[str, str]:
    """{ticker: quartile} for one month."""
    out: dict[str, str] = {}
    for q in Q_LABELS:
        for tk in month_holdings.get(q, []):
            out[tk] = q
    return out


def transition_flows(holdings: Holdings) -> dict[tuple[str, str], int]:
    """Aggregate flow counts {(src_label, dst_label): n} over adjacent months.

    src_label ∈ Q1..Q4, New; dst_label ∈ Q1..Q4, Dropped. A name present both
    months flows Qᵢ→Qⱼ; only in the earlier month → Qᵢ→Dropped; only in the later
    → New→Qⱼ. "Adjacent" = consecutive entries in the sorted month list.
    """
    months = sorted(holdings)
    flows: dict[tuple[str, str], int] = {}
    for cur, nxt in zip(months, months[1:], strict=False):
        prev_q = _ticker_quartile(holdings[cur])
        next_q = _ticker_quartile(holdings[nxt])
        for tk in set(prev_q) | set(next_q):
            src = prev_q.get(tk, NEW)
            dst = next_q.get(tk, DROPPED)
            flows[(src, dst)] = flows.get((src, dst), 0) + 1
    return flows


def sticky_tickers(holdings: Holdings, *, top_n: int = 10) -> dict[str, list[StickyRun]]:
    """Per quartile, the top-N longest unbroken tenures. A run breaks when the
    ticker changes quartile or leaves the holdings entirely.

    Each ticker contributes only its single longest run per quartile, so the list
    is distinct names. Ties broken by most-recent end, then ticker.
    """
    months = sorted(holdings)
    maps = {m: _ticker_quartile(holdings[m]) for m in months}

    # Longest run per (ticker, quartile): track open runs, close on change/exit.
    best: dict[tuple[str, str], StickyRun] = {}
    open_run: dict[str, tuple[str, str, int]] = {}  # ticker -> (quartile, start, length)

    def _close(tk: str) -> None:
        q, start, length = open_run.pop(tk)
        end_idx = months.index(start) + length - 1
        run = StickyRun(tk, q, length, start, months[end_idx])
        key = (tk, q)
        prev = best.get(key)
        if prev is None or run.length > prev.length:
            best[key] = run

    for m in months:
        cur = maps[m]
        for tk in list(open_run):
            if cur.get(tk) != open_run[tk][0]:  # quartile changed or ticker gone
                _close(tk)
        for tk, q in cur.items():
            if tk in open_run:
                qq, start, length = open_run[tk]
                open_run[tk] = (qq, start, length + 1)
            else:
                open_run[tk] = (q, m, 1)
    for tk in list(open_run):
        _close(tk)

    out: dict[str, list[StickyRun]] = {}
    for q in Q_LABELS:
        runs = [r for r in best.values() if r.quartile == q]
        # Stable multi-pass: ticker asc, then end desc, then length desc (primary).
        runs.sort(key=lambda r: r.ticker)
        runs.sort(key=lambda r: r.end, reverse=True)
        runs.sort(key=lambda r: r.length, reverse=True)
        out[q] = runs[:top_n]
    return out
