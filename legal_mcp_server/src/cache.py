"""Disk-backed cache for case-law search results.

Searching the judgment corpus is fast once synced, but the same proposition is
often searched repeatedly across sessions, and each call re-scans the DuckDB
files. This module caches successful search responses on disk keyed by the
exact query and filter parameters, with a 24-hour TTL.

The backing store is ``diskcache``: SQLite-backed, ACID-transactional (no
corrupt JSON under concurrent writes), with automatic LRU eviction against a
size limit. Blocking I/O is pushed off the event loop with ``asyncio.to_thread``.

Cache failures never break a search: a missed or corrupted entry falls
straight through to the live lookup, and a failed write is logged and ignored.
"""

import asyncio
import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import diskcache

from legal_mcp_server.src.settings import settings
from legal_mcp_server.utils.pylogger import get_python_logger

logger = get_python_logger()

CACHE_TTL_SECONDS = 86400  # 24 hours
CACHE_SIZE_LIMIT = 500 * 1024 * 1024  # 500 MB


@lru_cache(maxsize=1)
def _get_cache() -> diskcache.Cache:
    """Return the process-wide diskcache instance for case-law searches."""
    directory = Path(settings.LEGAL_DATA_PATH) / "cache" / "case_law"
    directory.mkdir(parents=True, exist_ok=True)
    return diskcache.Cache(str(directory), size_limit=CACHE_SIZE_LIMIT)


def _cache_key(
    query: str,
    court: Optional[str],
    from_date: Optional[str],
    to_date: Optional[str],
    judge: Optional[str],
    limit: int,
    page: int,
) -> str:
    raw = f"{query}|{court}|{from_date}|{to_date}|{judge}|{limit}|{page}"
    return f"search|{hashlib.sha256(raw.encode()).hexdigest()}"


async def get_cached_value(key: str) -> Optional[Any]:
    """Return an arbitrary cached payload by exact key, or None on miss/error."""
    try:
        return await asyncio.to_thread(_get_cache().get, key)
    except Exception as e:
        logger.debug(f"Cache read failed for {key}: {e}")
        return None


async def set_cached_value(data: Any, key: str) -> None:
    """Store an arbitrary payload under ``key`` with the shared TTL.

    Failures are logged and swallowed so caching can never break a lookup.
    """
    try:
        await asyncio.to_thread(_get_cache().set, key, data, expire=CACHE_TTL_SECONDS)
    except Exception as e:
        logger.debug(f"Cache write failed for {key}: {e}")


async def get_cached(
    query: str,
    court: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    judge: Optional[str] = None,
    limit: int = 20,
    page: int = 0,
) -> Optional[Any]:
    """Return the cached search response, or None on miss/expiry/error."""
    key = _cache_key(query, court, from_date, to_date, judge, limit, page)
    return await get_cached_value(key)


async def set_cached(
    data: Any,
    query: str,
    court: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    judge: Optional[str] = None,
    limit: int = 20,
    page: int = 0,
) -> None:
    """Store a successful search response under its query key.

    Failures are logged and swallowed so caching can never break a search.
    """
    key = _cache_key(query, court, from_date, to_date, judge, limit, page)
    await set_cached_value(data, key)


def clear_cache() -> int:
    """Delete all cached case-law search entries. Returns the count removed."""
    try:
        cache = _get_cache()
        count = int(len(cache))
        cache.clear()
        return count
    except Exception as e:
        logger.debug(f"Case-law cache clear failed: {e}")
        return 0
