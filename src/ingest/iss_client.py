"""Shared MOEX ISS client and its on-disk cache.

Every ingest module talks to the same host with the same headers and caches
responses under `.fill_cache/iss/<key>.json`. Only the client and the cache live
here — pagination stays with each module, because what counts as "no more data"
differs per endpoint and getting it wrong truncates history silently.

The cache has no TTL. Where the key carries a date window (prices, indices) a
re-run self-invalidates the next day; where the key is constant (listing,
securities, splits) only `force` refreshes it.

Payloads are stored compact: `.fill_cache/iss` is already ~600 MB and
pretty-printing would roughly double it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, cast

import httpx

from config import ISS_BASE_URL, ISS_HTTP_TIMEOUT_SECONDS

USER_AGENT = "moex-momentum/0.1"


def make_client() -> httpx.Client:
    return httpx.Client(
        base_url=ISS_BASE_URL,
        timeout=ISS_HTTP_TIMEOUT_SECONDS,
        params={"iss.meta": "off"},
        headers={"User-Agent": USER_AGENT},
    )


def make_async_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=ISS_BASE_URL,
        timeout=ISS_HTTP_TIMEOUT_SECONDS,
        params={"iss.meta": "off"},
        headers={"User-Agent": USER_AGENT},
    )


def cache_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / f"{key}.json"


def is_cached(cache_dir: Path | None, key: str) -> bool:
    """Whether a request would be served from disk.

    Callers that pace themselves need this before the call: sleeping between
    cache hits turns a cached full run into minutes of nothing.
    """
    return cache_dir is not None and cache_path(cache_dir, key).exists()


def _read(cache_dir: Path, key: str) -> dict[str, Any]:
    with cache_path(cache_dir, key).open(encoding="utf-8") as f:
        return cast(dict[str, Any], json.load(f))


def _store(cache_dir: Path, key: str, data: Any) -> None:
    cp = cache_path(cache_dir, key)
    cp.parent.mkdir(parents=True, exist_ok=True)
    tmp = cp.with_suffix(cp.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, cp)


def cached_get(
    client: httpx.Client,
    url_path: str,
    *,
    params: dict[str, str] | None = None,
    cache_dir: Path | None,
    cache_key: str,
    force: bool = False,
) -> dict[str, Any] | None:
    """GET with an on-disk cache. `None` for 404, which is never cached."""
    if is_cached(cache_dir, cache_key) and not force:
        assert cache_dir is not None
        return _read(cache_dir, cache_key)
    resp = client.get(url_path, params=params or {})
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    data: Any = resp.json()
    if cache_dir is not None:
        _store(cache_dir, cache_key, data)
    return cast(dict[str, Any], data)


async def cached_aget(
    client: httpx.AsyncClient,
    url_path: str,
    *,
    params: dict[str, str] | None = None,
    cache_dir: Path | None,
    cache_key: str,
    force: bool = False,
) -> dict[str, Any] | None:
    """Async twin of `cached_get`."""
    if is_cached(cache_dir, cache_key) and not force:
        assert cache_dir is not None
        return _read(cache_dir, cache_key)
    resp = await client.get(url_path, params=params or {})
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    data: Any = resp.json()
    if cache_dir is not None:
        _store(cache_dir, cache_key, data)
    return cast(dict[str, Any], data)
