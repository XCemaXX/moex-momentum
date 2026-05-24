"""MFD-specific constants + drift helper, vendored so `mfd_backfill/scripts/`
runs standalone without `momentum.config` / `momentum.io.prices` imports."""

from __future__ import annotations

from typing import Any

MFD_BASE_URL: str = "https://mfd.ru"
MFD_HTTP_TIMEOUT_SECONDS: float = 30.0
MFD_USER_AGENT: str = (
    "Mozilla/5.0 (compatible; moex-momentum-research/0.1; +https://github.com/xcemaxx/moex)"
)
MFD_OVERLAP_DRIFT_THRESHOLD: float = 0.005


def check_drift(
    ticker: str,  # noqa: ARG001
    iss_rows: list[dict[str, Any]],
    mfd_rows: list[dict[str, Any]],
    *,
    threshold: float = MFD_OVERLAP_DRIFT_THRESHOLD,
) -> list[tuple[str, float, float]]:
    """Return list of overlap (date, iss_close, mfd_close) tuples where
    relative drift exceeds `threshold`. Empty list = no drift."""
    iss_by = {r["date"]: r for r in iss_rows}
    mismatches: list[tuple[str, float, float]] = []
    for r in mfd_rows:
        d = r["date"]
        iss = iss_by.get(d)
        if iss is None:
            continue
        ic = float(iss["close"])
        mc = float(r["close"])
        if ic == 0.0:
            continue
        if abs(mc - ic) / abs(ic) > threshold:
            mismatches.append((d, ic, mc))
    return mismatches
