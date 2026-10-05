"""Minimal in-process rate limiting.

Used to slow abuse of authentication and other sensitive endpoints. This is a
per-process fixed-window limiter; it does not coordinate across replicas.
``# ponytail: per-process limiter; move to Redis/edge limiting when scaled out``
"""

from __future__ import annotations

import threading
import time

from app.exceptions import RateLimitedError


class RateLimiter:
    """Fixed-window rate limiter keyed by an arbitrary string (e.g. client IP)."""

    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        self._limit = limit
        self._window = window_seconds
        self._hits: dict[str, tuple[float, int]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        """Record a hit for ``key``; raise :class:`RateLimitedError` when exceeded."""
        now = time.monotonic()
        with self._lock:
            window_start, count = self._hits.get(key, (now, 0))
            if now - window_start >= self._window:
                window_start, count = now, 0
            count += 1
            self._hits[key] = (window_start, count)
            if len(self._hits) > 10_000:
                self._purge(now)
            if count > self._limit:
                raise RateLimitedError()

    def _purge(self, now: float) -> None:
        self._hits = {
            key: value for key, value in self._hits.items() if now - value[0] < self._window
        }
