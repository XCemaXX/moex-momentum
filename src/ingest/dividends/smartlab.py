"""smart-lab.ru per-payment dividend fetcher.

URL `https://smart-lab.ru/q/{TICKER}/dividend/`. The first table is per-payment
history; its header row is `[Тикер, дата T-1, дата отсечки, Период, дивиденд,
Цена акции, Див. доходность]`. `дата отсечки` is the record date, matching our
`registry_close`.

Both share classes live in the ordinary share's table — a pref ticker has no page
of its own, so we fall back to the ordinary one and filter by the Тикер column.

Covers the small-cap tail that dohod and tbank do not: after MOEX withdrew the
ISS dividends endpoint this is the only free source reaching those names.
Amounts are rounded to a few significant digits, so it ranks below every other
source in `SOURCE_PRIORITY`.

The page footer carries MOEX's restriction on redistributing exchange
information, which covers the price and yield columns. We read neither — the
declared payout and its record date are corporate-action facts, and prices come
from ISS anyway.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

from ingest.dividends.fetchers import CachedHttpFetcher

LOG = logging.getLogger(__name__)

_TICKER_HEADER = "Тикер"

# Recommended-then-voted-down payouts stay in the table, marked only by a CSS
# class — PLZL 2023 is one. Dropping the whole row before the table is parsed is
# the only place the markup still exists.
_CANCELLED_ROW_RE = re.compile(r"<tr\b[^>]*>(?:(?!</tr>).)*?dividend_canceled.*?</tr>", re.DOTALL)


def _parse_smartlab_date(s: str) -> str | None:
    """`"06.07.2026"` → `"2026-07-06"`. Anything else → None."""
    s = s.strip()
    try:
        d = date(int(s[6:10]), int(s[3:5]), int(s[0:2]))
    except (ValueError, IndexError):
        return None
    return d.isoformat()


def _parse_amount(s: str) -> float | None:
    """`"1 234,5₽"` → 1234.5. Requiring the rouble sign keeps a foreign-currency
    payout from being silently read as RUB."""
    t = s.replace("\xa0", "").replace(" ", "")
    if "₽" not in t:
        return None
    try:
        v = float(t.replace("₽", "").replace(",", "."))
    except ValueError:
        return None
    return v if v > 0 else None


class SmartLabFetcher(CachedHttpFetcher):
    source_tag = "skill_fill_smartlab"
    # Nominal-at-time: pre-split PLZL and GMKN rows match the stored series
    # exactly, both checked after their splits.
    restates_splits = False
    URL_TEMPLATE = "https://smart-lab.ru/q/{ticker}/dividend/"

    def fetch(self, ticker: str) -> list[dict[str, Any]]:
        rows = self._fetch_page(ticker, want=ticker)
        if not rows and ticker.endswith("P"):
            rows = self._fetch_page(ticker[:-1], want=ticker)
        return rows

    def _fetch_page(self, page_ticker: str, *, want: str) -> list[dict[str, Any]]:
        html = self._cached_text(
            cache_key=f"smartlab/{page_ticker.upper()}.html",
            url=self.URL_TEMPLATE.format(ticker=page_ticker.upper()),
        )
        if not html:
            return []
        # Lazy pandas import: keeps `--help` on unrelated CLI commands fast.
        import io as _io  # noqa: PLC0415

        import pandas as pd  # noqa: PLC0415

        # Pin the parser: the default flavour falls back to bs4, which pandas
        # services with html5lib — not a dependency of this project.
        try:
            tables = pd.read_html(_io.StringIO(_CANCELLED_ROW_RE.sub("", html)), flavor="lxml")
        except ValueError:
            tables = []
        if not tables:
            LOG.warning("smartlab %s: no tables on the page", page_ticker)
            return []
        df = tables[0]
        out: list[dict[str, Any]] = []
        seen_header = False
        for _, row in df.iterrows():
            cells = [str(c).strip() for c in row.tolist()]
            if not seen_header:
                # A caption row precedes the header, so anchor on the header itself.
                seen_header = cells[0] == _TICKER_HEADER
                continue
            if cells[0] != want.upper():
                continue
            reg = _parse_smartlab_date(cells[2])
            amt = _parse_amount(cells[4])
            if reg is None or amt is None:
                continue
            out.append(
                {
                    "registry_close": reg,
                    "amount": amt,
                    "currency": "RUB",
                    "source": self.source_tag,
                }
            )
        if not seen_header:
            LOG.warning("smartlab %s: dividend table header not found", page_ticker)
        out.sort(key=lambda r: r["registry_close"])
        return out
