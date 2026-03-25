"""Generic Cache protocol and LRU cache implementation."""

from collections import OrderedDict
from typing import Generic, Hashable, Protocol, TypeVar

K_contra = TypeVar("K_contra", bound=Hashable, contravariant=True)
V = TypeVar("V")


class Cache(Protocol[K_contra, V]):
    """Structural protocol for an async key-value cache."""

    async def get(self, key: K_contra) -> V | None: ...
    async def set(self, key: K_contra, value: V) -> None: ...


K = TypeVar("K", bound=Hashable)


class LRUCache(Generic[K, V]):
    """In-memory LRU cache with optional next-layer write-through/read-through.

    Uses an OrderedDict to track insertion/access order.  The least-recently-used
    entry sits at the *front* of the dict; the most-recently-used entry sits at
    the *end*.

    If a ``next_layer`` cache is supplied:
    - on a local miss, the next layer is consulted and the result is populated locally.
    - on every set, the value is propagated to the next layer.
    """

    def __init__(self, maxsize: int, next_layer: Cache[K, V] | None = None) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be at least 1")
        self._maxsize = maxsize
        self._next_layer = next_layer
        self._store: OrderedDict[K, V] = OrderedDict()

    async def get(self, key: K) -> V | None:
        """Return the value for *key*, or None if not found.

        On a local hit the entry is moved to the MRU (end) position.
        On a local miss the next layer (if any) is consulted; a hit there
        populates the local store before returning.
        """
        if key in self._store:
            self._store.move_to_end(key)
            return self._store[key]

        if self._next_layer is not None:
            value = await self._next_layer.get(key)
            if value is not None:
                await self._set_local(key, value)
                return value

        return None

    async def set(self, key: K, value: V) -> None:
        """Store *value* under *key*.

        If the key already exists locally its value is updated in place and
        the entry is moved to the MRU position.  Otherwise, if the store is
        full, the LRU (front) entry is evicted before inserting.

        The value is always propagated to the next layer when one is present.
        """
        await self._set_local(key, value)

        if self._next_layer is not None:
            await self._next_layer.set(key, value)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _set_local(self, key: K, value: V) -> None:
        """Write to the local OrderedDict, evicting the LRU entry if needed."""
        if key in self._store:
            self._store[key] = value
            self._store.move_to_end(key)
        else:
            if len(self._store) >= self._maxsize:
                self._store.popitem(last=False)  # evict LRU (front)
            self._store[key] = value
            # new entries are already at the end of an OrderedDict
