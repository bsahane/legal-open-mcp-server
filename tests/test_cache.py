"""Tests for the disk-backed case-law search cache (legal_mcp_server.src.cache).

The cache is a pure optimisation, so its contract is: round-trip what you
stored, keep different queries apart, never raise - a broken or missing
cache must degrade to "no caching", never break a search.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from legal_mcp_server.src import cache
from legal_mcp_server.src.settings import settings


@pytest.fixture
def cache_root(tmp_path: Path):
    """Point the search cache at a throwaway directory for one test."""
    with patch.object(settings, "LEGAL_DATA_PATH", str(tmp_path)):
        cache._get_cache.cache_clear()
        yield tmp_path
    # Drop the cached instance bound to the deleted tmp dir so later tests
    # rebuild against their own location.
    cache._get_cache.cache_clear()


class TestRoundTrip:
    """Store-and-fetch behaviour."""

    @pytest.mark.asyncio
    async def test_set_then_get_returns_payload(self, cache_root):
        """A stored response comes back byte-identical."""
        payload = {"status": "success", "results": [1, 2, 3]}
        await cache.set_cached(payload, query="cheque dishonour", limit=20)
        assert await cache.get_cached("cheque dishonour", limit=20) == payload

    @pytest.mark.asyncio
    async def test_different_params_do_not_collide(self, cache_root):
        """Each distinct parameter combination is its own entry."""
        await cache.set_cached({"n": 1}, query="q")
        await cache.set_cached({"n": 2}, query="q", court="Bombay")
        assert await cache.get_cached("q") == {"n": 1}
        assert await cache.get_cached("q", court="Bombay") == {"n": 2}

    @pytest.mark.asyncio
    async def test_miss_returns_none(self, cache_root):
        """An unknown key yields None, not an exception."""
        assert await cache.get_cached("never stored") is None


class TestFailureModes:
    """Caching must never break a search."""

    @pytest.mark.asyncio
    async def test_read_failure_returns_none(self, cache_root):
        """If the store cannot be read, get_cached degrades to a miss."""
        with patch.object(cache, "_get_cache", side_effect=RuntimeError("disk gone")):
            assert await cache.get_cached("q") is None

    @pytest.mark.asyncio
    async def test_write_failure_is_swallowed(self, cache_root):
        """If the store cannot be written, set_cached stays silent."""
        with patch.object(cache, "_get_cache", side_effect=RuntimeError("disk gone")):
            await cache.set_cached({"n": 1}, query="q")

    @pytest.mark.asyncio
    async def test_expiry_removes_entry(self, cache_root):
        """An expired entry is treated as a miss."""
        with patch.object(cache, "CACHE_TTL_SECONDS", 0):
            await cache.set_cached({"n": 1}, query="old query")
        assert await cache.get_cached("old query") is None


class TestClear:
    """clear_cache wipes every entry."""

    @pytest.mark.asyncio
    async def test_clear_removes_all_entries(self, cache_root):
        """Every stored entry is gone after a clear, and the count matches."""
        for i in range(3):
            await cache.set_cached({"i": i}, query=f"query {i}")
        removed = cache.clear_cache()
        assert removed == 3
        assert await cache.get_cached("query 0") is None

    def test_clear_failure_returns_zero(self, cache_root):
        """A failed clear reports zero rather than raising."""
        with patch.object(cache, "_get_cache", side_effect=RuntimeError("disk gone")):
            assert cache.clear_cache() == 0


class TestClose:
    """close_cache releases the store but the module keeps working."""

    @pytest.mark.asyncio
    async def test_close_then_reuse(self, cache_root):
        """After closing, a new lookup transparently reopens the store."""
        await cache.set_cached({"n": 1}, query="before close")
        cache.close_cache()
        assert await cache.get_cached("before close") == {"n": 1}

    def test_close_is_repeatable_and_tolerant(self, cache_root):
        """Closing twice, or with the store already broken, never raises."""
        cache.close_cache()
        with patch.object(cache, "_get_cache", side_effect=RuntimeError("disk gone")):
            cache.close_cache()
