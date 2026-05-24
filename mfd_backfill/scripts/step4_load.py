"""Step 4: parse cached CSVs → per-SECID JSONL.

Reads (SECID, mfd_id) pairs from `mfd_backfill/data/mfd_ticker_ids.json` and
matching `mfd_backfill/cache/raw/{mfd_id}.csv` files. Writes
`mfd_backfill/data/prices_mfd/{SECID}.jsonl` atomically. Offline (0 HTTP),
idempotent.

Optional `--drift-report` runs `_lib.check_drift` over every resolved SECID
with ISS counterpart and writes `mfd_backfill/data/drift_report.md`.

Run:
    python mfd_backfill/scripts/step4_load.py
    python mfd_backfill/scripts/step4_load.py --drift-report
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from momentum.io.atomic import read_jsonl, write_jsonl_atomic

sys.path.insert(0, str(Path(__file__).parent))
from _lib import MFD_OVERLAP_DRIFT_THRESHOLD, check_drift  # noqa: E402

LOG = logging.getLogger("step4_load")

EXPECTED_HEADER_PREFIX = ("TICKER", "PER", "DATE")

PriceRow = dict[str, Any]


def _strip_angle(s: str) -> str:
    s = s.strip()
    if s.startswith("<") and s.endswith(">"):
        return s[1:-1]
    return s


def _to_float(s: str) -> float | None:
    s = s.strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _to_int(s: str) -> int | None:
    s = s.strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _yyyymmdd_to_iso(s: str) -> str | None:
    s = s.strip()
    if len(s) != 8 or not s.isdigit():
        return None
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def parse_mfd_csv(text: str) -> list[PriceRow]:
    """`<TICKER>;<PER>;<DATE>;<TIME>;<OPEN>;<HIGH>;<LOW>;<CLOSE>;<VOL>;<OPENINT>`
    → PriceRow list. Date converted from yyyyMMdd to ISO. board='MFD'."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    header = [_strip_angle(p).upper() for p in lines[0].split(";")]
    if tuple(header[:3]) != EXPECTED_HEADER_PREFIX:
        raise ValueError(f"unexpected header: {lines[0]!r}")
    idx = {n: i for i, n in enumerate(header)}
    for col in ("DATE", "OPEN", "HIGH", "LOW", "CLOSE", "VOL"):
        if col not in idx:
            raise ValueError(f"missing column {col!r}: {header}")
    out: list[PriceRow] = []
    for ln in lines[1:]:
        p = [x.strip() for x in ln.split(";")]
        if len(p) < len(header):
            continue
        iso = _yyyymmdd_to_iso(p[idx["DATE"]])
        if iso is None:
            raise ValueError(f"bad date {p[idx['DATE']]!r}")
        close = _to_float(p[idx["CLOSE"]])
        if close is None:
            continue
        out.append(
            {
                "date": iso,
                "open": _to_float(p[idx["OPEN"]]),
                "high": _to_float(p[idx["HIGH"]]),
                "low": _to_float(p[idx["LOW"]]),
                "close": close,
                "volume": _to_int(p[idx["VOL"]]),
                "value": None,  # mfd export has no trade-value column
                "board": "MFD",
            }
        )
    return out


def load_csv(cache_dir: Path, mfd_id: int) -> str | None:
    p = cache_dir / "raw" / f"{mfd_id}.csv"
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8", errors="replace")


def _write_jsonl(out_dir: Path, secid: str, rows: list[PriceRow]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl_atomic(out_dir / f"{secid}.jsonl", rows)


def run_load(
    resolved: dict[str, int],
    *,
    cache_dir: Path,
    output_dir: Path,
) -> dict[str, dict[str, Any]]:
    """Return {secid: {mfd_id, rows, first_date, last_date, status}}."""
    stats: dict[str, dict[str, Any]] = {}
    for secid, mfd_id in sorted(resolved.items()):
        text = load_csv(cache_dir, mfd_id)
        if text is None:
            stats[secid] = {"mfd_id": mfd_id, "status": "no-cache", "rows": 0}
            continue
        try:
            rows = parse_mfd_csv(text)
        except ValueError as exc:
            stats[secid] = {"mfd_id": mfd_id, "status": f"parse-error: {exc}", "rows": 0}
            LOG.warning("%s (id=%d): parse fail: %s", secid, mfd_id, exc)
            continue
        if not rows:
            stats[secid] = {"mfd_id": mfd_id, "status": "empty", "rows": 0}
            continue
        _write_jsonl(output_dir, secid, rows)
        stats[secid] = {
            "mfd_id": mfd_id,
            "status": "ok",
            "rows": len(rows),
            "first_date": rows[0]["date"],
            "last_date": rows[-1]["date"],
        }
    return stats


def _drift_report(
    stats: dict[str, dict[str, Any]],
    *,
    prices_iss_dir: Path,
    output_dir: Path,
    report_path: Path,
) -> None:
    """For each ok-loaded SECID with both ISS+mfd data, compute drift summary."""
    rows: list[tuple[str, int, int, int, float, str]] = []
    for secid, s in stats.items():
        if s.get("status") != "ok":
            continue
        iss_p = prices_iss_dir / f"{secid}.jsonl"
        mfd_p = output_dir / f"{secid}.jsonl"
        if not iss_p.exists() or not mfd_p.exists():
            continue
        iss = read_jsonl(iss_p)
        mfd = read_jsonl(mfd_p)
        if not iss or not mfd:
            continue
        overlap = len({r["date"] for r in iss} & {r["date"] for r in mfd})
        if overlap == 0:
            continue
        mism = check_drift(secid, iss, mfd, threshold=MFD_OVERLAP_DRIFT_THRESHOLD)
        max_d = max((abs(mc - ic) / ic for _, ic, mc in mism), default=0.0)
        sample = mism[0] if mism else None
        sample_s = f"{sample[0]} ISS={sample[1]:.4f} mfd={sample[2]:.4f}" if sample else "-"
        rows.append((secid, len(mism), overlap, len(mfd), max_d, sample_s))
    rows.sort(key=lambda r: -r[1])  # worst-drift first
    lines = [
        "# mfd vs ISS drift report",
        "",
        f"Drift threshold: {MFD_OVERLAP_DRIFT_THRESHOLD:.2%} per-day on close.",
        "",
        "| SECID | drift days | overlap | mfd rows | max abs drift | sample |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for secid, d, o, total, mx, samp in rows:
        lines.append(f"| {secid} | {d} | {o} | {total} | {mx:.2%} | {samp} |")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOG.info("wrote drift report → %s (%d tickers analysed)", report_path, len(rows))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Step 4: cache → data/prices_mfd/")
    ap.add_argument("--resolved", type=Path, default=Path("mfd_backfill/data/mfd_ticker_ids.json"))
    ap.add_argument("--cache-dir", type=Path, default=Path("mfd_backfill/cache"))
    ap.add_argument("--output-dir", type=Path, default=Path("mfd_backfill/data/prices_mfd"))
    ap.add_argument("--drift-report", action="store_true")
    ap.add_argument("--prices-iss-dir", type=Path, default=Path("data/prices_iss"))
    ap.add_argument(
        "--report-path",
        type=Path,
        default=Path("mfd_backfill/data/drift_report.md"),
    )
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    resolved: dict[str, int] = {
        k: int(v) for k, v in json.loads(args.resolved.read_text(encoding="utf-8")).items()
    }
    LOG.info("loading %d resolved SECIDs from %s", len(resolved), args.resolved)
    stats = run_load(resolved, cache_dir=args.cache_dir, output_dir=args.output_dir)

    counts = {"ok": 0, "empty": 0, "no-cache": 0, "parse-error": 0}
    rows_total = 0
    for s in stats.values():
        status = s.get("status", "")
        bucket = "parse-error" if status.startswith("parse-error") else status
        counts[bucket] = counts.get(bucket, 0) + 1
        rows_total += s.get("rows", 0)
    LOG.info(
        "loaded: ok=%d empty=%d no-cache=%d parse-error=%d  total_rows=%d",
        counts["ok"],
        counts["empty"],
        counts["no-cache"],
        counts["parse-error"],
        rows_total,
    )

    if args.drift_report:
        _drift_report(
            stats,
            prices_iss_dir=args.prices_iss_dir,
            output_dir=args.output_dir,
            report_path=args.report_path,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
