"""Structured response schema, parsing and coverage validation."""

from __future__ import annotations

import pytest
from app.providers.errors import ProviderError
from app.translation.structured import (
    map_translations,
    parse_translation_items,
    response_json_schema,
)


def test_schema_is_generated_from_models() -> None:
    schema = response_json_schema()
    assert schema["title"] == "TranslationBatch"
    item = schema["$defs"]["TranslationItem"]
    assert set(item["properties"]) == {"segment_id", "translation"}
    assert item.get("additionalProperties") is False


@pytest.mark.parametrize(
    "content",
    [
        '{"translations":[{"segment_id":"s1","translation":"x"}]}',
        '[{"segment_id":"s1","translation":"x"}]',
        '{"s1":"x"}',
        '```json\n{"translations":[{"segment_id":"s1","translation":"x"}]}\n```',
        'Sure! {"translations":[{"segment_id":"s1","translation":"x"}]} done.',
    ],
)
def test_parses_supported_shapes(content: str) -> None:
    items = parse_translation_items(content)
    assert [(item.segment_id, item.translation) for item in items] == [("s1", "x")]


def test_parses_marked_segment_format() -> None:
    # Models that ignore response_format echo the prompt's `[[id]] text` shape.
    content = "[[s1]] premier\n[[s2]] second\nline encore"
    items = parse_translation_items(content)
    assert [(item.segment_id, item.translation) for item in items] == [
        ("s1", "premier"),
        ("s2", "second\nline encore"),
    ]


@pytest.mark.parametrize("content", ["", "not json", '{"translations":"oops"}', "{"])
def test_invalid_content_rejected(content: str) -> None:
    with pytest.raises(ProviderError):
        parse_translation_items(content)


def test_map_translations_success() -> None:
    items = parse_translation_items('{"s1":"a","s2":"b"}')
    assert map_translations(items, ["s1", "s2"]) == {"s1": "a", "s2": "b"}


def test_missing_segment_rejected() -> None:
    items = parse_translation_items('{"translations":[{"segment_id":"s1","translation":"a"}]}')
    with pytest.raises(ProviderError):
        map_translations(items, ["s1", "s2"])


def test_unknown_segment_rejected_in_strict_mode() -> None:
    items2 = parse_translation_items(
        '{"translations":[{"segment_id":"s1","translation":"a"},{"segment_id":"zz","translation":"b"}]}'
    )
    with pytest.raises(ProviderError):
        map_translations(items2, ["s1"], strict=True)
    assert map_translations(items2, ["s1"], strict=False) == {"s1": "a"}


def test_unknown_segment_ignored_when_tolerating_missing() -> None:
    # A stray id from the model must not fail the whole batch.
    items = parse_translation_items(
        '{"translations":[{"segment_id":"s1","translation":"a"},'
        '{"segment_id":"stray","translation":"x"}]}'
    )
    assert map_translations(items, ["s1"], tolerate_missing=True) == {"s1": "a"}


def test_duplicate_segment_rejected() -> None:
    items = parse_translation_items(
        '{"translations":[{"segment_id":"s1","translation":"a"},{"segment_id":"s1","translation":"b"}]}'
    )
    with pytest.raises(ProviderError):
        map_translations(items, ["s1"])


def test_empty_translation_rejected() -> None:
    items = parse_translation_items('{"translations":[{"segment_id":"s1","translation":"  "}]}')
    with pytest.raises(ProviderError):
        map_translations(items, ["s1"])
