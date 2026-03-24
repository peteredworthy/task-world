"""Unit tests for the LRUCache implementation.

No mocking - all tests use real LRUCache instances.
"""

from orchestrator.git.diff import LRUCache


class TestLRUCacheBasics:
    async def test_get_empty_returns_none(self) -> None:
        cache: LRUCache[str, str] = LRUCache(maxsize=10)
        result = await cache.get("missing")
        assert result is None

    async def test_set_then_get_returns_value(self) -> None:
        cache: LRUCache[str, str] = LRUCache(maxsize=10)
        await cache.set("key", "value")
        result = await cache.get("key")
        assert result == "value"

    async def test_update_existing_key(self) -> None:
        """Setting the same key twice updates the value without evicting."""
        cache: LRUCache[str, str] = LRUCache(maxsize=2)
        await cache.set("key", "first")
        await cache.set("key", "second")
        assert await cache.get("key") == "second"
        # The cache should still hold exactly one logical entry for "key"
        # Verify no phantom eviction occurred by checking another key survives.
        await cache.set("other", "ok")
        assert await cache.get("key") == "second"
        assert await cache.get("other") == "ok"

    async def test_maxsize_one(self) -> None:
        """With maxsize=1 each new set evicts the previous entry."""
        cache: LRUCache[str, str] = LRUCache(maxsize=1)
        await cache.set("a", "alpha")
        assert await cache.get("a") == "alpha"

        await cache.set("b", "beta")
        assert await cache.get("b") == "beta"
        # "a" must have been evicted
        assert await cache.get("a") is None


class TestLRUCacheEviction:
    async def test_lru_eviction_evicts_oldest(self) -> None:
        """When maxsize=2 and 3 items are set, the first item is evicted."""
        cache: LRUCache[str, str] = LRUCache(maxsize=2)
        await cache.set("a", "alpha")
        await cache.set("b", "beta")
        # Cache is full; inserting "c" must evict "a" (the LRU entry)
        await cache.set("c", "gamma")

        assert await cache.get("a") is None
        assert await cache.get("b") == "beta"
        assert await cache.get("c") == "gamma"

    async def test_get_refreshes_lru_order(self) -> None:
        """get() moves the accessed item to MRU; the OTHER item is evicted next."""
        cache: LRUCache[str, str] = LRUCache(maxsize=2)
        await cache.set("a", "alpha")
        await cache.set("b", "beta")

        # Access "a" to promote it to MRU; "b" becomes the LRU
        assert await cache.get("a") == "alpha"

        # Inserting a third item should evict "b", not "a"
        await cache.set("c", "gamma")

        assert await cache.get("a") == "alpha"  # survives — was promoted
        assert await cache.get("b") is None  # evicted — became LRU after get("a")
        assert await cache.get("c") == "gamma"


class TestLRUCacheNextLayer:
    async def test_next_layer_read_through(self) -> None:
        """On a local miss the value is fetched from next_layer and cached locally."""
        l2: LRUCache[str, str] = LRUCache(maxsize=10)
        await l2.set("key", "from-l2")

        l1: LRUCache[str, str] = LRUCache(maxsize=10, next_layer=l2)

        # Cold L1 — should fall through to L2
        result = await l1.get("key")
        assert result == "from-l2"

        # A second get should now be served from L1 (it was populated above)
        # We verify by clearing L2 and confirming L1 still returns the value.
        l2._store.clear()
        assert await l1.get("key") == "from-l2"

    async def test_next_layer_write_through(self) -> None:
        """set() writes to both local and next_layer."""
        l2: LRUCache[str, str] = LRUCache(maxsize=10)
        l1: LRUCache[str, str] = LRUCache(maxsize=10, next_layer=l2)

        await l1.set("key", "value")

        # Both layers should hold the value
        assert await l1.get("key") == "value"
        assert await l2.get("key") == "value"

    async def test_multilevel_cache(self) -> None:
        """L1(maxsize=1) wrapping L2(maxsize=10): value evicted from L1 survives in L2
        and is re-read from L2 back into L1 on the next get."""
        l2: LRUCache[str, str] = LRUCache(maxsize=10)
        l1: LRUCache[str, str] = LRUCache(maxsize=1, next_layer=l2)

        await l1.set("a", "alpha")  # L1 holds "a"; L2 holds "a"

        # Insert "b" — evicts "a" from L1 but L2 still has it
        await l1.set("b", "beta")
        assert "a" not in l1._store  # evicted from L1

        # Getting "a" should read through to L2 and repopulate L1
        result = await l1.get("a")
        assert result == "alpha"
        assert "a" in l1._store  # now back in L1
