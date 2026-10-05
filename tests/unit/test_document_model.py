"""Canonical model identity and versioned serialization."""

from __future__ import annotations

import pytest
from app.documents.ids import block_id, section_id
from app.documents.model import (
    BlockType,
    CanonicalDocument,
    DocumentMetadata,
    Section,
    TextBlock,
)
from app.documents.serialization import (
    canonical_storage_key,
    from_json_bytes,
    to_json_bytes,
)
from app.exceptions import ValidationError


def _document() -> CanonicalDocument:
    return CanonicalDocument(
        document_id="doc-1",
        source_type="epub",
        metadata=DocumentMetadata(title="Book", authors=["A"]),
        sections=[
            Section(
                id=section_id(0),
                source_order=0,
                title="Chapter 1",
                blocks=[
                    TextBlock(
                        id=block_id(0),
                        type=BlockType.HEADING,
                        source_order=0,
                        source_text="Chapter",
                    ),
                    TextBlock(
                        id=block_id(1),
                        type=BlockType.PARAGRAPH,
                        source_order=1,
                        source_text="Hello world.",
                        attributes={"plain_text": "Hello world."},
                    ),
                    TextBlock(id=block_id(2), type=BlockType.SEPARATOR, source_order=2),
                ],
            )
        ],
    )


def test_ids_are_deterministic() -> None:
    assert block_id(0) == "block_0000"
    assert block_id(41) == "block_0041"
    assert section_id(3) == "section_003"


def test_text_blocks_exclude_non_translatable() -> None:
    document = _document()
    ids = [block.id for block in document.text_blocks()]
    assert ids == ["block_0000", "block_0001"]
    assert document.find_block("block_0001") is not None
    assert document.find_block("missing") is None


def test_serialization_roundtrip() -> None:
    document = _document()
    restored = from_json_bytes(to_json_bytes(document))
    assert restored == document
    assert restored.canonical_model_version == 1


def test_unsupported_version_rejected() -> None:
    payload = to_json_bytes(_document()).replace(
        b'"canonical_model_version":1', b'"canonical_model_version":99'
    )
    with pytest.raises(ValidationError):
        from_json_bytes(payload)


def test_storage_key_is_deterministic() -> None:
    assert canonical_storage_key("doc-1") == "documents/doc-1/canonical/v1.json"
    with pytest.raises(ValidationError):
        canonical_storage_key("  ")
