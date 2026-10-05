"""PocketBase-backed language registry."""

from __future__ import annotations

from app.language.models import Direction
from app.language.registry import PocketBaseLanguageRegistry
from app.repositories.languages import LanguageRepository


async def test_resolve_exact_and_variant(pb, fake_pb) -> None:
    fake_pb.seed(
        "languages",
        {
            "language_code": "fa",
            "name": "Persian",
            "native_name": "فارسی",
            "direction": "rtl",
            "script_code": "Arab",
            "default_locale": "fa-IR",
            "enabled": True,
        },
    )
    registry = PocketBaseLanguageRegistry(LanguageRepository(pb))

    base = await registry.resolve("fa")
    assert base is not None
    assert base.direction is Direction.RTL
    assert base.is_rtl is True
    assert base.script == "Arab"

    # A variant tag resolves to its base language record.
    variant = await registry.resolve("fa-IR")
    assert variant is not None
    assert variant.direction is Direction.RTL


async def test_unknown_language_returns_none(pb) -> None:
    registry = PocketBaseLanguageRegistry(LanguageRepository(pb))
    assert await registry.resolve("xx-YY") is None


async def test_list_enabled(pb, fake_pb) -> None:
    fake_pb.seed(
        "languages",
        {"language_code": "de", "name": "German", "direction": "ltr", "enabled": True},
    )
    fake_pb.seed(
        "languages",
        {"language_code": "xx", "name": "Hidden", "direction": "ltr", "enabled": False},
    )
    registry = PocketBaseLanguageRegistry(LanguageRepository(pb))
    languages = await registry.list()
    assert [lang.iso639_1 for lang in languages] == ["de"]
