"""Disk orchestration: raw prices + splits + dividends → per-ticker monthly CSV.

Pure-function modules:
    - adjustments.apply (apply_splits_to_prices, adjust_dividend_amounts)
    - momentum.monthly (monthly_total_returns)

This module wires them to the on-disk CSV layout. Output goes to
`data/momentum/monthly/{TICKER}.csv` — output of the momentum compute domain.

Two modes:
- Default (incremental verify): recompute is full but a sha256 hash of the
  pre-tail block (rows older than `INCREMENTAL_RECOMPUTE_MONTHS`) is compared
  against `_baseline_hashes.json`. Mismatch → fail-loud, suggesting a new
  split or pre-tail dividend invalidated the baseline.
- `--from-scratch`: same recompute, hash mismatch is silently accepted and the
  new hash overwrites the baseline. Used after backfill batches.

The hash compares records bytes (CSV-serialized via the same schema as the
output file), so the hash is stable across runs as long as the rows match.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from adjustments.apply import adjust_dividend_amounts, apply_splits_to_prices
from config import DIVIDEND_TAX, INCREMENTAL_RECOMPUTE_MONTHS, MASS_DRIFT_THRESHOLD
from momentum.monthly import monthly_total_returns
from storage.records import read_records, write_records_atomic
from storage.schemas import DIV_CASTS, MONTHLY_FIELDS, PRICE_CASTS, SPLIT_CASTS
from tickers import enumerate_tickers

LOG = logging.getLogger(__name__)


def _records_to_csv_bytes(records: list[dict[str, object]]) -> bytes:
    """Serialize records to the same CSV bytes that `write_records_atomic` writes.
    Used for hashing — keeps the hash stable across runs.
    """
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=list(MONTHLY_FIELDS), restval="", lineterminator="\n")
    writer.writeheader()
    for rec in records:
        writer.writerow(rec)
    return buf.getvalue().encode("utf-8")


def _pre_tail_hash(records: list[dict[str, object]], tail_months: int) -> str:
    """sha256 of pre-tail rows (everything except the last `tail_months`)."""
    pre = records[:-tail_months] if len(records) > tail_months else []
    h = hashlib.sha256()
    h.update(_records_to_csv_bytes(pre))
    return h.hexdigest()


class IncrementalDriftError(ValueError):
    """Pre-tail hash diverged from the committed baseline. Operator should
    inspect inputs (new split or pre-tail dividend?) and, if the drift is
    expected, rerun the offending tickers with `--from-scratch` to update
    `_baseline_hashes.json`."""


def load_baseline_hashes(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object of ticker→sha256")
    return {str(k): str(v) for k, v in data.items()}


def save_baseline_hashes(path: Path, hashes: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(hashes, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


@dataclass(frozen=True)
class MonthlyMeta:
    rows: int
    first_month: str | None
    last_month: str | None


def _df_to_records(df: pd.DataFrame) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for period, row in df.iterrows():
        rec: dict[str, object] = {
            "month": str(period),
            "month_end_date": pd.Timestamp(row["month_end_date"]).date().isoformat(),
            "close_adj": float(row["close_adj"]),
            "monthly_value_rub": float(row["monthly_value_rub"]),
            "price_return": _maybe_nan(row["price_return"]),
            "div_return": float(row["div_return"]),
            "total_return": _maybe_nan(row["total_return"]),
        }
        out.append(rec)
    return out


def _maybe_nan(v: object) -> float | None:
    f = float(v)  # type: ignore[arg-type]
    if math.isnan(f):
        return None
    return f


def compute_one(
    ticker: str,
    *,
    prices_iss_dir: Path,
    dividends_dir: Path,
    splits_dir: Path,
    output_dir: Path,
    baseline_hashes: dict[str, str],
    from_scratch: bool,
    tax: float = DIVIDEND_TAX,
    tail_months: int = INCREMENTAL_RECOMPUTE_MONTHS,
) -> MonthlyMeta:
    prices = read_records(prices_iss_dir / f"{ticker}.csv", casts=PRICE_CASTS)
    if not prices:
        return MonthlyMeta(rows=0, first_month=None, last_month=None)
    splits = read_records(splits_dir / f"{ticker}.csv", casts=SPLIT_CASTS)
    dividends = read_records(dividends_dir / f"{ticker}.csv", casts=DIV_CASTS)

    prices_adj_df = apply_splits_to_prices(prices, splits)
    if prices_adj_df.empty:
        return MonthlyMeta(rows=0, first_month=None, last_month=None)
    dividends_adj = adjust_dividend_amounts(dividends, splits, ticker=ticker)
    monthly = monthly_total_returns(prices_adj_df, dividends_adj, tax=tax, ticker=ticker)
    records = _df_to_records(monthly)

    new_hash = _pre_tail_hash(records, tail_months)
    baseline = baseline_hashes.get(ticker)
    if baseline is None:
        baseline_hashes[ticker] = new_hash
    elif baseline != new_hash:
        if from_scratch:
            baseline_hashes[ticker] = new_hash
            LOG.info("baseline updated for %s (from-scratch)", ticker)
        else:
            raise IncrementalDriftError(
                f"drift detected for {ticker}: pre-tail rows differ from committed "
                f"baseline. Likely a new split or pre-tail dividend lands in the "
                f"older history. Inspect data/splits/{ticker}.csv and "
                f"data/dividends/{ticker}.csv, then rerun with --from-scratch "
                f"if the drift is expected."
            )

    out_path = output_dir / f"{ticker}.csv"
    write_records_atomic(out_path, records, fieldnames=MONTHLY_FIELDS)
    first = str(monthly.index[0]) if len(monthly) else None
    last = str(monthly.index[-1]) if len(monthly) else None
    return MonthlyMeta(rows=len(records), first_month=first, last_month=last)


def compute_all(
    *,
    prices_iss_dir: Path,
    dividends_dir: Path,
    splits_dir: Path,
    output_dir: Path,
    baseline_hashes_path: Path | None = None,
    ticker_filter: list[str] | None = None,
    from_scratch: bool = False,
    tax: float = DIVIDEND_TAX,
) -> dict[str, MonthlyMeta]:
    output_dir.mkdir(parents=True, exist_ok=True)
    hashes_path = (
        baseline_hashes_path
        if baseline_hashes_path is not None
        else output_dir / "_baseline_hashes.json"
    )
    baseline_hashes = load_baseline_hashes(hashes_path)
    tickers: list[str]
    if ticker_filter:
        tickers = list(ticker_filter)
    else:
        tickers = enumerate_tickers(prices_iss_dir)
    result: dict[str, MonthlyMeta] = {}
    drifted: list[str] = []
    mass_warned = False
    for t in tickers:
        try:
            meta = compute_one(
                t,
                prices_iss_dir=prices_iss_dir,
                dividends_dir=dividends_dir,
                splits_dir=splits_dir,
                output_dir=output_dir,
                baseline_hashes=baseline_hashes,
                from_scratch=from_scratch,
                tax=tax,
            )
        except IncrementalDriftError as exc:
            LOG.error("%s", exc)
            drifted.append(t)
            if not mass_warned and len(drifted) >= MASS_DRIFT_THRESHOLD:
                LOG.warning(
                    "mass-drift detected: %d+ tickers drifted from baseline. "
                    "This looks like a post-ingest rebuild rather than a single "
                    "missed split/dividend. Cancel and rerun with --from-scratch "
                    "to rebless baselines in one pass.",
                    MASS_DRIFT_THRESHOLD,
                )
                mass_warned = True
            continue
        result[t] = meta
        LOG.info(
            "monthly ticker=%s rows=%d first=%s last=%s",
            t,
            meta.rows,
            meta.first_month,
            meta.last_month,
        )
    save_baseline_hashes(hashes_path, baseline_hashes)
    if drifted:
        if len(drifted) >= MASS_DRIFT_THRESHOLD:
            sample = ", ".join(sorted(drifted)[:5])
            raise IncrementalDriftError(
                f"mass-drift: {len(drifted)} tickers diverged from baseline "
                f"(e.g. {sample}, ...). Looks like a post-ingest rebuild — "
                f"rerun with --from-scratch to rebless all baselines."
            )
        raise IncrementalDriftError(
            f"drift in {len(drifted)} ticker(s): {', '.join(sorted(drifted))}. "
            f"Inspect inputs and rerun with --from-scratch if expected."
        )
    return result


def write_manifest_section(manifest_path: Path, result: dict[str, MonthlyMeta]) -> None:
    manifest: dict[str, dict[str, dict[str, object]]] = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    )
    section = manifest.setdefault("monthly", {})
    for tk, m in result.items():
        if m.rows == 0:
            continue
        section[tk] = {"rows": m.rows, "first": m.first_month, "last": m.last_month}
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(manifest_path)
