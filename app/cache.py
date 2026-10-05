"""Tiny bounded TTL cache for request-path deduplication.

Used to collapse repeated, expensive, *idempotent* lookups that would otherwise
hit PocketBase on every request (session validation, personal workspace
resolution). An entry is only ever trusted for ``ttl_seconds``; callers choose
that window deliberately, trading a bounded staleness for removing a network
round trip.

Not a distributed cache: each worker process keeps its own window, so entries do
not invalidate across replicas.

``# ponytail: in-process TTL cache, bounded and self-pruning; add a shared cache
only if cross-replica invalidation ever matters``
"""

from __future__ import annotations

import time


class TTLCache[T]:
    """A small, bounded, monotonic-clock TTL cache."""

    def __init__(
        self,
        *,
        ttl_seconds: float,
        maxsize: int = 1024,
        clock: object = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if maxsize <= 0:
            raise ValueError("maxsize must be positive")
        self._ttl = ttl_seconds
        self._maxsize = maxsize
        self._clock = clock  # callable; injectable for tests
        self._data: dict[str, tuple[float, T]] = {}

    def get(self, key: str) -> T | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        expiry, value = entry
        if expiry < self._clock():  # type: ignore[operator]
            self._data.pop(key, None)
            return None
        return value

    def set(self, key: str, value: T) -> None:
        if key not in self._data and len(self._data) >= self._maxsize:
            self._prune()
        self._data[key] = (self._clock() + self._ttl, value)  # type: ignore[operator]

    def pop(self, key: str) -> None:
        self._data.pop(key, None)

    def _prune(self) -> None:
        now = self._clock()  # type: ignore[operator]
        for key in [k for k, (expiry, _) in self._data.items() if expiry < now]:
            self._data.pop(key, None)
        # Still full: dict preserves insertion order, so the head is the entry
        # with the earliest expiry. Drop the oldest to stay bounded.
        while len(self._data) >= self._maxsize:
            self._data.pop(next(iter(self._data)))
