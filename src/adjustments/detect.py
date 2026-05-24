"""Detector of suspicious daily returns — flags days that look like an
unrecorded split / bonus / corporate action.

Rules — a day is flagged if **all** of:
1. `|raw_return| > SUSPICIOUS_RETURN_THRESHOLD` (default 0.30).
2. No dividend record with `registry_close == that day`.
3. No split record within ±1 trading-day window.
4. Not in `_acked.json` within ±1 trading-day window.
5. Daily turnover > `MIN_DAILY_VALUE_FOR_DETECT` (default 100k RUB)
   — kills single-trade penny days where one fill at an absurd price
   manufactures a "return" out of nothing.

Detector runs on **raw** prices (pre-adjustment). Adjusted prices would
mask exactly the splits we are trying to surface — see phase 7 plan.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

import pandas as pd

from config import MIN_DAILY_VALUE_FOR_DETECT, SUSPICIOUS_RETURN_THRESHOLD
from storage.records import read_records
from storage.schemas import DIV_CASTS, PRICE_CASTS, SPLIT_CASTS
from tickers import enumerate_tickers

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class Suspicion:
    ticker: str
    date: str
    raw_return: float
    daily_value_rub: float
    reason: str


def _shadow_dates(idx: pd.DatetimeIndex, target: pd.Timestamp) -> set[pd.Timestamp]:
    """Trading-day ±1 window around `target` using the price index.

    If `target` lands on a non-trading day, we anchor on its nearest neighbours
    (handles weekend gaps, ex-vs-effective day drift).
    """
    if len(idx) == 0:
        return set()
    pos = int(cast(Any, idx.searchsorted(target)))
    out: set[pd.Timestamp] = set()
    if pos < len(idx) and idx[pos] == target:
        out.add(idx[pos])
        if pos > 0:
            out.add(idx[pos - 1])
        if pos < len(idx) - 1:
            out.add(idx[pos + 1])
    else:
        if pos > 0:
            out.add(idx[pos - 1])
        if pos < len(idx):
            out.add(idx[pos])
    return out


def _expand_dates_to_window(idx: pd.DatetimeIndex, dates: list[str]) -> set[pd.Timestamp]:
    out: set[pd.Timestamp] = set()
    for d in dates:
        out |= _shadow_dates(idx, pd.Timestamp(d))
    return out


def _prices_to_df(records: list[dict[str, Any]]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=["close", "value"]).astype({"close": float, "value": float})
    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    keep = [c for c in ("close", "value") if c in df.columns]
    df = df[keep].astype(float)
    # close == 0 on MOEX = no trade / data artefact. Leaves +inf in pct_change otherwise.
    return df[df["close"] > 0]


def detect_suspicious(
    ticker: str,
    prices: list[dict[str, Any]],
    dividends: list[dict[str, Any]],
    splits: list[dict[str, Any]],
    acked_dates: list[str],
    *,
    return_threshold: float = SUSPICIOUS_RETURN_THRESHOLD,
    min_daily_value: float = MIN_DAILY_VALUE_FOR_DETECT,
) -> list[Suspicion]:
    """Run detector for one ticker. Inputs are JSONL records."""
    df = _prices_to_df(prices)
    if len(df) < 2:
        return []
    df["ret"] = df["close"].pct_change()
    df = df.dropna(subset=["ret"])
    idx = cast(pd.DatetimeIndex, df.index)

    div_dates = {pd.Timestamp(r["registry_close"]) for r in dividends}
    split_window = _expand_dates_to_window(idx, [r["date"] for r in splits])
    acked_window = _expand_dates_to_window(idx, acked_dates)

    out: list[Suspicion] = []
    for raw_ts, row in df.iterrows():
        ts = cast(pd.Timestamp, raw_ts)
        ret = float(row["ret"])
        if abs(ret) <= return_threshold:
            continue
        if ts in div_dates:
            continue
        if ts in split_window or ts in acked_window:
            continue
        value = float(row.get("value", 0.0) or 0.0)
        if value <= min_daily_value:
            continue
        out.append(
            Suspicion(
                ticker=ticker,
                date=ts.date().isoformat(),
                raw_return=ret,
                daily_value_rub=value,
                reason="abs_return_above_threshold",
            )
        )
    return out


def load_acked(path: Path) -> dict[str, list[str]]:
    """`_acked.json` schema: list of {ticker, date, comment}.

    Returns {ticker: [date, ...]}.
    """
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, list):
        raise ValueError(f"{path}: expected a JSON array")
    out: dict[str, list[str]] = {}
    for i, rec in enumerate(raw):
        if not isinstance(rec, dict):
            raise ValueError(f"{path}[{i}]: expected an object")
        for fld in ("ticker", "date"):
            if not rec.get(fld):
                raise ValueError(f"{path}[{i}]: missing field {fld!r}")
        out.setdefault(rec["ticker"].upper(), []).append(rec["date"])
    return out


def run_all(
    *,
    prices_iss_dir: Path,
    dividends_dir: Path,
    splits_dir: Path,
    acked_path: Path,
) -> list[Suspicion]:
    """Detect over all tickers that have a prices file."""
    acked = load_acked(acked_path)
    out: list[Suspicion] = []
    for ticker in enumerate_tickers(prices_iss_dir):
        prices = read_records(prices_iss_dir / f"{ticker}.csv", casts=PRICE_CASTS)
        divs = read_records(dividends_dir / f"{ticker}.csv", casts=DIV_CASTS)
        splits = read_records(splits_dir / f"{ticker}.csv", casts=SPLIT_CASTS)
        out.extend(detect_suspicious(ticker, prices, divs, splits, acked.get(ticker, [])))
    return out


def save_suspicious(path: Path, suspicions: list[Suspicion]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = [asdict(s) for s in suspicions]
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(path)
