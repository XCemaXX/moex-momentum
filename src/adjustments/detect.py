"""Detector of suspicious daily returns — flags days that look like an
unrecorded split / bonus / corporate action.

Rules — a day is flagged if **all** of:
1. `|raw_return| > SUSPICIOUS_RETURN_THRESHOLD` (default 0.30).
2. No dividend record with `registry_close == that day`.
3. No split record within ±1 trading-day window.
4. Not in `_acked.json` within ±1 trading-day window.
5. Daily turnover > `MIN_DAILY_VALUE_FOR_DETECT` (default 100k RUB)
   — kills single-trade penny days where one fill at an absurd price
   manufactures a "return" out of nothing. A `sustained_rebase` candidate is
   exempt: it is filtered by four agreeing signals, not by liquidity.

Detector runs on **raw** prices (pre-adjustment). Adjusted prices would
mask exactly the splits we are trying to surface — see phase 7 plan.

Every flag carries a `reason`. Only `sustained_rebase` is a split candidate; the
rest are kept because they diagnose other things — a board switch points at the
price source, a flag next to a payout at the dividend anchor. Narrowing the
detector itself would throw those away, so the classification is a layer on top.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from config import (
    MIN_DAILY_VALUE_FOR_DETECT,
    REBASE_FLATNESS_MAX,
    REBASE_GAP_MIN_DAYS,
    REBASE_ROUNDNESS_MAX,
    REBASE_SHARE_RANGE,
    REBASE_WINDOW,
    SPLIT_MATCH_DAYS,
    SUSPICIOUS_RETURN_THRESHOLD,
)
from storage.records import read_records, write_json_atomic
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
    keep = [c for c in ("close", "value", "board") if c in df.columns]
    df = df[keep]
    for col in ("close", "value"):
        if col in df.columns:
            df[col] = df[col].astype(float)
    # close == 0 on MOEX = no trade / data artefact. Leaves +inf in pct_change otherwise.
    return df[df["close"] > 0]


# Ratios a nominal change actually takes: whole numbers plus the few halves.
_ROUND_FACTORS: tuple[float, ...] = tuple(
    sorted(
        {float(n) for n in range(2, 201)}
        | {1000.0, 5000.0, 1.1, 1.2, 1.25, 1.5, 2.5, 12.5}
        | {1 / n for n in range(2, 201)}
        | {1 / 1000.0, 1 / 5000.0, 1 / 1.1, 1 / 1.2, 1 / 1.25, 1 / 1.5, 1 / 2.5, 1 / 12.5}
    )
)


def _is_sustained_rebase(df: pd.DataFrame, pos: int) -> bool:
    """Does the price step to a new plateau and stay there, by a round factor?

    A split moves the whole level once; a limit move or an illiquid print does
    not. Four independent signals have to agree, which is what separates the
    handful of real events from thousands of ordinary large moves.
    """
    win = REBASE_WINDOW
    if pos < win or pos > len(df) - win - 1:
        return False
    closes = df["close"].to_numpy(dtype=float)
    before, after = closes[pos - win : pos], closes[pos : pos + win]
    factor = float(np.median(before) / np.median(after))
    if factor <= 0:
        return False
    log_f = math.log(factor)
    if abs(log_f) < math.log(1.05):
        return False

    # The step must be one day's worth, not a slow drift or a run of limit days.
    share = math.log(closes[pos - 1] / closes[pos]) / log_f
    roundness = min(abs(log_f - math.log(r)) for r in _ROUND_FACTORS)
    lb, la = np.log(before), np.log(after)
    spread = max(
        float(np.median(np.abs(lb - np.median(lb)))),
        float(np.median(np.abs(la - np.median(la)))),
    )
    return bool(
        REBASE_SHARE_RANGE[0] <= share <= REBASE_SHARE_RANGE[1]
        and roundness <= REBASE_ROUNDNESS_MAX
        and spread / abs(log_f) <= REBASE_FLATNESS_MAX
        and (df.index[pos] - df.index[pos - 1]).days >= REBASE_GAP_MIN_DAYS
    )


def _classify(df: pd.DataFrame, pos: int, div_dates: set[pd.Timestamp], *, rebase: bool) -> str:
    if rebase:
        return "sustained_rebase"
    if "board" in df.columns and df["board"].iloc[pos] != df["board"].iloc[pos - 1]:
        return "board_change"
    ts = cast(pd.Timestamp, df.index[pos])
    if any(abs((ts - d).days) <= SPLIT_MATCH_DAYS for d in div_dates):
        return "near_dividend"
    return "limit_move"


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
    for pos, (raw_ts, row) in enumerate(df.iterrows()):
        ts = cast(pd.Timestamp, raw_ts)
        ret = float(row["ret"])
        if abs(ret) <= return_threshold:
            continue
        if ts in div_dates:
            continue
        if ts in split_window or ts in acked_window:
            continue
        value = float(row.get("value", 0.0) or 0.0)
        rebase = _is_sustained_rebase(df, pos)
        # The turnover gate kills penny-print noise, but a split on an illiquid
        # name is exactly the one that rots unnoticed. Four agreeing signals are
        # a stronger filter than turnover, so a rebase candidate skips the gate.
        if value <= min_daily_value and not rebase:
            continue
        out.append(
            Suspicion(
                ticker=ticker,
                date=ts.date().isoformat(),
                raw_return=ret,
                daily_value_rub=value,
                reason=_classify(df, pos, div_dates, rebase=rebase),
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
    write_json_atomic(path, [asdict(s) for s in suspicions], sort_keys=False)
