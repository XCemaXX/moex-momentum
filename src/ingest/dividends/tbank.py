"""Tinkoff (tbank.ru) SPA-bootstrap dividend fetcher.

Endpoint: `https://www.tbank.ru/invest/stocks/{T}/dividends/`. One anonymous
GET, payload ~700 KB HTML. Dividend records live in an embedded
`<script type="application/json">` block under
`stores.investDividends.{T}.dividends` as
`{reestr: "YYYY-MM-DDTHH:MM:SS...", dividend: {value: float, currency: str}}`.

Catalog depth ~2017 (broker-side limit, not access mode — confirmed by user
spot-check in mobile app 2026-05-16). Per-share-class: pref tickers like
LNZLP have their own page.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any

from ingest.dividends.fetchers import CachedHttpFetcher

LOG = logging.getLogger(__name__)

# All <script type="application/json"> blocks on the page. The dividend payload
# is the largest one (page bootstrap); we scan all and pick the first that
# contains stores.investDividends.
_SCRIPT_RE = re.compile(
    r'<script\b[^>]*type="application/json"[^>]*>(.*?)</script>',
    re.DOTALL,
)


def _extract_dividends_payload(html: str, ticker: str) -> list[dict[str, Any]] | None:
    """Walk every JSON-script on the page, return raw dividends list or None."""
    for m in _SCRIPT_RE.finditer(html):
        raw = m.group(1).strip()
        if "investDividends" not in raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        stores = payload.get("stores") if isinstance(payload, dict) else None
        if not isinstance(stores, dict):
            continue
        inv = stores.get("investDividends")
        if not isinstance(inv, dict):
            continue
        # Tinkoff keys by ticker uppercase, sometimes by ISIN — try both shapes.
        bucket = inv.get(ticker.upper()) or inv.get(ticker)
        if not isinstance(bucket, dict):
            # Fall back: take the single bucket if there's exactly one.
            non_meta = [v for v in inv.values() if isinstance(v, dict) and "dividends" in v]
            if len(non_meta) == 1:
                bucket = non_meta[0]
            else:
                continue
        divs = bucket.get("dividends")
        if isinstance(divs, list):
            return divs
    return None


def _parse_reestr_date(s: str) -> str | None:
    """`"2024-06-17T00:00:00+03:00"` → `"2024-06-17"`. None if malformed."""
    if not s or len(s) < 10:
        return None
    try:
        return date.fromisoformat(s[:10]).isoformat()
    except ValueError:
        return None


class TbankFetcher(CachedHttpFetcher):
    source_tag = "skill_fill_tbank"
    URL_TEMPLATE = "https://www.tbank.ru/invest/stocks/{ticker}/dividends/"

    def fetch(self, ticker: str) -> list[dict[str, Any]]:
        html = self._cached_text(
            cache_key=f"tbank/{ticker}.html",
            url=self.URL_TEMPLATE.format(ticker=ticker),
        )
        if not html:
            return []
        divs = _extract_dividends_payload(html, ticker)
        if divs is None:
            LOG.info("tbank %s: dividends block not found", ticker)
            return []
        out: list[dict[str, Any]] = []
        for entry in divs:
            if not isinstance(entry, dict):
                continue
            reg = _parse_reestr_date(entry.get("reestr") or "")
            div_block = entry.get("dividend") or {}
            raw_value = div_block.get("value")
            if raw_value is None:
                continue
            try:
                amt = float(raw_value)
            except (TypeError, ValueError):
                continue
            if reg is None or amt <= 0:
                continue
            currency = (div_block.get("currency") or "RUB").upper()
            if currency == "SUR":
                currency = "RUB"
            out.append(
                {
                    "registry_close": reg,
                    "amount": amt,
                    "currency": currency,
                    "source": self.source_tag,
                    "registry_close_source": "tbank_reestr",
                }
            )
        out.sort(key=lambda r: r["registry_close"])
        return out
