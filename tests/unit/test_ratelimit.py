"""Unit tests for the rate limiter."""

from __future__ import annotations

import pytest
from app.exceptions import RateLimitedError
from app.security.ratelimit import RateLimiter


def test_allows_within_limit() -> None:
    limiter = RateLimiter(3, window_seconds=60)
    for _ in range(3):
        limiter.check("client-a")


def test_blocks_over_limit() -> None:
    limiter = RateLimiter(2, window_seconds=60)
    limiter.check("client-a")
    limiter.check("client-a")
    with pytest.raises(RateLimitedError):
        limiter.check("client-a")


def test_keys_are_independent() -> None:
    limiter = RateLimiter(1, window_seconds=60)
    limiter.check("client-a")
    limiter.check("client-b")
