"""Shared interface and plumbing for external dividend fetchers.

`DividendFetcher` is the structural contract consumers (`fill.py`, the cascade
backfill script) depend on. `CachedHttpFetcher` factors out the cache-then-HTTP
dance the concrete fetchers (dohod/tbank/yahoo) all repeat — each only differs
in URL shape, cache filename, and how it parses the response.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

HttpGet = Callable[[str], str | None]


class DividendFetcher(Protocol):
    source_tag: str

    def fetch(self, ticker: str) -> list[dict[str, Any]]: ...


class CachedHttpFetcher:
    """Base: holds the http_get callable + optional disk cache.

    Subclasses implement `fetch` and call `_cached_text` with their own cache
    key and URL.
    """

    def __init__(
        self,
        http_get: HttpGet,
        cache_dir: Path | None = None,
        *,
        force_refresh: bool = False,
    ) -> None:
        self._http_get = http_get
        self._cache_dir = cache_dir
        self._force_refresh = force_refresh

    def _cached_text(self, *, cache_key: str, url: str) -> str | None:
        """Raw response text, reading/writing the disk cache.

        Caches the raw response before any parsing — a parse failure must not
        cost a network round-trip on re-run.

        The cache has no TTL, so a monthly run would otherwise read last month's
        snapshot and silently miss every payout declared since. `force_refresh`
        re-fetches, keeping the old entry when the fetch fails.
        """
        cache_path = self._cache_dir / cache_key if self._cache_dir else None
        cached = (
            cache_path.read_text(encoding="utf-8") if cache_path and cache_path.exists() else None
        )
        if cached is not None and not self._force_refresh:
            return cached
        text = self._http_get(url)
        if text is None:
            return cached
        if cache_path:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(text, encoding="utf-8")
        return text
