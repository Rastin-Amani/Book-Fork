"""Exact translation memory: pair-scoped, approved-only reuse."""

from __future__ import annotations

from app.repositories.knowledge import TranslationMemoryRepository
from app.translation.memory import (
    TranslationMemory,
    memory_hash,
    normalize_for_match,
)


def test_normalize_for_match_is_language_agnostic() -> None:
    assert normalize_for_match("  Hello\tWorld  ") == "hello world"
    assert normalize_for_match("Ｆｕｌｌ") == "full"  # noqa: RUF001 - NFKC test


def test_hash_is_pair_scoped() -> None:
    a = memory_hash("en", "fa", "hello")
    b = memory_hash("en", "de", "hello")
    c = memory_hash("en", "fa", "hello")
    assert a == c and a != b


async def test_lookup_requires_approved(pb, fake_pb) -> None:
    fake_pb.seed(
        "translation_memory_entries",
        {
            "source_language": "en",
            "target_language": "fa",
            "source_text": "Hello",
            "normalized_source_text": "hello",
            "translation": "سلام",
            "approved": False,
        },
    )
    memory = TranslationMemory(TranslationMemoryRepository(pb))
    assert await memory.lookup("en", "fa", "Hello") is None


async def test_lookup_returns_best_approved(pb, fake_pb) -> None:
    fake_pb.seed(
        "translation_memory_entries",
        {
            "source_language": "en",
            "target_language": "fa",
            "normalized_source_text": "hello",
            "source_text": "Hello",
            "translation": "سلام",
            "approved": True,
            "quality": 0.5,
        },
    )
    fake_pb.seed(
        "translation_memory_entries",
        {
            "source_language": "en",
            "target_language": "fa",
            "normalized_source_text": "hello",
            "source_text": "Hello",
            "translation": "درود",
            "approved": True,
            "quality": 0.9,
        },
    )
    memory = TranslationMemory(TranslationMemoryRepository(pb))
    hit = await memory.lookup("en", "fa", "Hello")
    assert hit is not None and hit.translation == "درود"


async def test_pair_isolation(pb, fake_pb) -> None:
    fake_pb.seed(
        "translation_memory_entries",
        {
            "source_language": "en",
            "target_language": "de",
            "normalized_source_text": "hello",
            "translation": "Hallo",
            "approved": True,
        },
    )
    memory = TranslationMemory(TranslationMemoryRepository(pb))
    assert await memory.lookup("en", "fa", "Hello") is None


async def test_store_records_normalized_and_hash(pb, fake_pb) -> None:
    memory = TranslationMemory(TranslationMemoryRepository(pb))
    entry = await memory.store(
        source_language="en",
        target_language="fa",
        source_text="  Hello ",
        translation="سلام",
    )
    assert entry.normalized_source_text == "hello"
    assert entry.source_hash == memory_hash("en", "fa", "hello")
