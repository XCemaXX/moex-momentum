"""MOEX register-closing-dates export — which dividend registers actually closed.

`https://web.moex.com/moex-web-icdb-api/api/v1/export/register-closing-dates/csv`
returns the whole history in one CSV: `Эмитент,Дата события,Адрес сайта,Тип события`.
It carries dates but no amounts, so it is a completeness check rather than a
source — and since MOEX withdrew the ISS dividends endpoint it is the only
first-party answer left to "did this share pay?".

The response is cp1251 with no charset header, hence a bytes-in interface.
Dates are `MM/DD/YYYY`. Rows from roughly 2021 on embed the SECID in the issuer
string; older ones name the issuer only and are skipped.
"""

from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from ingest.dividends.merge import DATE_TOL_DAYS
from storage.records import read_records
from storage.schemas import DIV_CASTS

REGISTER_URL = (
    "https://web.moex.com/moex-web-icdb-api/api/v1/export/"
    "register-closing-dates/csv?language=1&separator=1"
)

# `ПАО "Татнефть" им. В.Д. Шашина - 2-03-00161-A, TATNP [Акция привилегированная]`
_SECID_RE = re.compile(r",\s*([A-Z][A-Z0-9]{2,5})\s*\[")

# Registers MOEX only recommends are not events that happened.
_CONFIRMED_EVENT = "закрытие реестра"


def parse_register(payload: bytes) -> list[dict[str, str]]:
    """`{"ticker", "record_date"}` per confirmed, SECID-tagged register closing."""
    text = payload.decode("cp1251", errors="replace")
    out: list[dict[str, str]] = []
    for row in csv.DictReader(io.StringIO(text)):
        if (row.get("Тип события") or "").strip() != _CONFIRMED_EVENT:
            continue
        m = _SECID_RE.search(row.get("Эмитент") or "")
        if not m:
            continue
        stamp = (row.get("Дата события") or "")[:10]
        try:
            month, day, year = (int(x) for x in stamp.split("/"))
            when = date(year, month, day)
        except ValueError:
            continue
        out.append({"ticker": m.group(1), "record_date": when.isoformat()})
    out.sort(key=lambda r: (r["record_date"], r["ticker"]))
    return out


def _first_price_date(path: Path) -> str | None:
    """First traded day, read without loading the whole series."""
    with path.open(encoding="utf-8", newline="") as f:
        rows = csv.reader(f)
        header = next(rows, None)
        first = next(rows, None)
    if not header or not first:
        return None
    return first[header.index("date")]


def missing_payouts(
    register: list[dict[str, str]],
    dividends_dir: Path,
    prices_dir: Path,
    *,
    since: str,
    until: str,
    acked: dict[str, set[int]] | None = None,
    date_tol_days: int = DATE_TOL_DAYS,
) -> list[dict[str, Any]]:
    """Register closings in `[since, until]` with no stored dividend near them.

    Only tickers we hold prices for are reported — the export spans the whole
    exchange, and names outside the universe are not gaps. Membership is keyed on
    prices, not on the dividend file, so a share's first-ever payout still counts.

    The export is not purely dividend registers — CBOM's 2015 entry looks like a
    shareholder-meeting list — so `acked` suppresses (ticker, year) pairs confirmed
    to have paid nothing.
    """
    acked = acked or {}
    by_ticker: dict[str, list[str]] = defaultdict(list)
    for row in register:
        if since <= row["record_date"] <= until:
            by_ticker[row["ticker"]].append(row["record_date"])

    out: list[dict[str, Any]] = []
    for ticker, dates in sorted(by_ticker.items()):
        price_path = prices_dir / f"{ticker}.csv"
        if not price_path.exists():
            continue
        # A register that closed before the share traded belongs to the pre-IPO
        # holders — BAZA and BTBR both have one. No listed share was entitled.
        listed_from = _first_price_date(price_path)
        stored = {
            r["registry_close"]
            for r in read_records(dividends_dir / f"{ticker}.csv", casts=DIV_CASTS)
        }
        acked_years = acked.get(ticker, set())
        for when in sorted(dates):
            if listed_from is not None and when < listed_from:
                continue
            if int(when[:4]) in acked_years:
                continue
            anchor = date.fromisoformat(when)
            window = {
                (anchor + timedelta(days=k)).isoformat()
                for k in range(-date_tol_days, date_tol_days + 1)
            }
            if not (window & stored):
                out.append({"ticker": ticker, "record_date": when})
    return out
