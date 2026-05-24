"""Dividend-gap detector.

For each ticker with prices: years that have >= `min_active_months` of trading
activity but zero dividend records. Acked years (no-div confirmed manually) are
suppressed. Output feeds task-005 fill workflow.

Lives in `corporate/` because the rule joins price activity with dividend
absence — same pattern as `corporate/detect.py` (suspicious returns).
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from storage.records import read_records
from storage.schemas import DIV_CASTS, PRICE_CASTS


def _active_months_per_year(prices: list[dict[str, Any]]) -> dict[int, set[int]]:
    """For a price-records list, group by (year → set of months that contain rows)."""
    out: dict[int, set[int]] = defaultdict(set)
    for r in prices:
        d = date.fromisoformat(r["date"])
        out[d.year].add(d.month)
    return out


def _div_years(divs: list[dict[str, Any]]) -> set[int]:
    return {date.fromisoformat(r["registry_close"]).year for r in divs}


def load_acked(path: Path) -> dict[str, set[int]]:
    """`_acked_no_div.json` schema: `{TICKER: {"YYYY": "reason", ...}, ...}`."""
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a JSON object")
    out: dict[str, set[int]] = {}
    for ticker, years in raw.items():
        if not isinstance(years, dict):
            raise ValueError(f"{path}[{ticker!r}]: expected object")
        out[ticker.upper()] = {int(y) for y in years}
    return out


def compute_gaps(
    prices_dir: Path,
    dividends_dir: Path,
    *,
    acked: dict[str, set[int]] | None = None,
    min_active_months: int = 6,
) -> list[dict[str, Any]]:
    """For each ticker with prices: years with >= min_active_months activity but
    zero dividend records, minus acked (ticker, year) pairs.
    """
    acked = acked or {}
    out: list[dict[str, Any]] = []
    for price_path in sorted(prices_dir.glob("*.csv")):
        ticker = price_path.stem
        prices = read_records(price_path, casts=PRICE_CASTS)
        if not prices:
            continue
        active = _active_months_per_year(prices)
        div_path = dividends_dir / f"{ticker}.csv"
        divs = read_records(div_path, casts=DIV_CASTS)
        years_with_div = _div_years(divs)
        ack_set = acked.get(ticker, set())
        for year, months in sorted(active.items()):
            if len(months) < min_active_months:
                continue
            if year in years_with_div or year in ack_set:
                continue
            out.append({"ticker": ticker, "year": year, "reason": "no_record_for_year"})
    return out


def save_gaps(path: Path, gaps: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(gaps, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(path)
