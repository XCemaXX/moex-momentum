"""dohod.ru per-payment dividend fetcher.

URL `https://www.dohod.ru/ik/analytics/dividend/{ticker}` returns an HTML page
with several tables; the third (`pd.read_html(...)[2]`) is per-payment history.

Columns (verified 2026-05-12): `[Дата объявления дивиденда, Дата закрытия
реестра, Год для учета дивиденда, Дивиденд]`. Decimal `.`, dates `DD.MM.YYYY`.
Forecast / `n/a` rows yield None registry → dropped.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from ingest.dividends.fetchers import CachedHttpFetcher

LOG = logging.getLogger(__name__)


def _parse_dohod_date(s: str) -> str | None:
    """`"25.06.2004"` → `"2004-06-25"`. Strings with `(прогноз)` or `n/a` → None."""
    s = s.strip()
    if not s or "прогноз" in s or s.lower() == "n/a":
        return None
    try:
        d = date(int(s[6:10]), int(s[3:5]), int(s[0:2]))
    except (ValueError, IndexError):
        return None
    return d.isoformat()


class DohodFetcher(CachedHttpFetcher):
    source_tag = "skill_fill_dohod"
    URL_TEMPLATE = "https://www.dohod.ru/ik/analytics/dividend/{ticker}"

    def fetch(self, ticker: str) -> list[dict[str, Any]]:
        html = self._cached_text(
            cache_key=f"dohod/{ticker.lower()}.html",
            url=self.URL_TEMPLATE.format(ticker=ticker.lower()),
        )
        if not html:
            return []
        # Lazy pandas import: keeps `--help` on unrelated CLI commands fast.
        import io as _io  # noqa: PLC0415

        import pandas as pd  # noqa: PLC0415

        tables = pd.read_html(_io.StringIO(html))
        if len(tables) < 3:
            LOG.warning("dohod %s: expected >=3 tables, got %d", ticker, len(tables))
            return []
        df = tables[2]
        out: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            reg = _parse_dohod_date(str(row.iloc[1]))
            if reg is None:
                continue
            try:
                amt = float(row.iloc[3])
            except (ValueError, TypeError):
                continue
            if amt <= 0:
                continue
            out.append(
                {
                    "registry_close": reg,
                    "amount": amt,
                    "currency": "RUB",
                    "source": self.source_tag,
                }
            )
        return out
