"""Unit tests for the bounded TTL cache."""

from __future__ import annotations

from app.cache import TTLCache


def test_get_returns_none_for_missing_key() -> None:
    assert TTLCache(ttl_seconds=10).get("nope") is None


def test_entry_expires() -> None:
    now = [0.0]
    cache: TTLCache[str] = TTLCache(ttl_seconds=10, clock=lambda: now[0])
    cache.set("k", "v")
    now[0] = 9.9
    assert cache.get("k") == "v"
    now[0] = 10.1
    assert cache.get("k") is None


def test_bounded_drops_oldest_without_growing() -> None:
    now = [0.0]
    cache: TTLCache[int] = TTLCache(ttl_seconds=100, maxsize=2, clock=lambda: now[0])
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)
    assert cache.get("a") is None  # oldest evicted
    assert cache.get("b") == 2
    assert cache.get("c") == 3


def test_pop_removes_entry() -> None:
    cache: TTLCache[str] = TTLCache(ttl_seconds=10)
    cache.set("k", "v")
    cache.pop("k")
    assert cache.get("k") is None
