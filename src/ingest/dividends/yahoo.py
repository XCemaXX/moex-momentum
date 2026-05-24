"""Yahoo Finance v8 chart-API dividend fetcher.

Endpoint:
    https://query1.finance.yahoo.com/v8/finance/chart/{T}.ME
        ?events=div&period1=0&period2={now}&interval=1d

Anonymous (no crumb/cookie for the chart endpoint). Payload schema (verified
2026-05-16 on 14 tickers):

    chart.result[0].meta.currency           "RUB"
    chart.result[0].meta.exchangeName       "MCX"
    chart.result[0].events.dividends        {unix_ts_str: {amount, date}}
    chart.error                             null on success, object on error

`date` is the **ex-dividend date** (~3-7 business days before MOEX
registry-close), tagged as `registry_close_source="yahoo_ex_div"` so the
cascade in `merge.py` keeps the higher-priority source's date when an ISS /
dohod / tbank record covers the same payout.

Amounts are split-adjusted RUB — cross-check against ISS post-2014 matched
LNZLP byte-for-byte (8.71, 110.00, 13.87, 3699.27, ...) at registry-close.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from ingest.dividends.fetchers import CachedHttpFetcher

LOG = logging.getLogger(__name__)


class YahooFetcher(CachedHttpFetcher):
    source_tag = "skill_fill_yahoo"
    URL_TEMPLATE = (
        "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}.ME"
        "?events=div&period1=0&period2={period2}&interval=1d"
    )

    def fetch(self, ticker: str) -> list[dict[str, Any]]:
        period2 = int(datetime.now(UTC).timestamp())
        text = self._cached_text(
            cache_key=f"yahoo/{ticker}.json",
            url=self.URL_TEMPLATE.format(ticker=ticker, period2=period2),
        )
        if text is None:
            return []
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            LOG.warning("yahoo %s: JSON decode failed: %s", ticker, exc)
            return []
        chart = payload.get("chart", {})
        if chart.get("error"):
            LOG.info("yahoo %s: chart.error=%s", ticker, chart["error"])
            return []
        result = chart.get("result") or []
        if not result:
            return []
        r0 = result[0]
        meta = r0.get("meta", {})
        currency = meta.get("currency", "RUB")
        divs_raw = r0.get("events", {}).get("dividends") or {}
        out: list[dict[str, Any]] = []
        for entry in divs_raw.values():
            ts = entry.get("date")
            amt = entry.get("amount")
            if ts is None or amt is None:
                continue
            amount = float(amt)
            if amount <= 0:
                continue
            ex_date = datetime.fromtimestamp(int(ts), UTC).date().isoformat()
            out.append(
                {
                    "registry_close": ex_date,
                    "amount": amount,
                    "currency": currency,
                    "source": self.source_tag,
                    "registry_close_source": "yahoo_ex_div",
                }
            )
        out.sort(key=lambda r: r["registry_close"])
        return out
