"""Canonical document model.

This is the format-agnostic heart of Book Fork's document engine. EPUB/PDF
adapters convert *into* it, and output adapters render *out of* it. No
translation or LLM code may depend on EPUB/PDF internals — only on this model.

Design notes:
- Block ``source_text`` is the translatable string. For rich formats it is the
  block's inner markup (inline tags included) so that inline formatting survives
  translation; markup is protected before it reaches a provider by
  :class:`app.documents.placeholders.PlaceholderProtector`.
- ``attributes["plain_text"]`` carries the text-only content, used for language
  detection and sentence segmentation.
- IDs are deterministic (see ``ids.py``) and stable for a fixed source, and are
  not derived from array position alone — every block also carries a
  ``source_ref`` anchor when the source format provides one.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

CANONICAL_MODEL_VERSION = 1


class BlockType(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    QUOTE = "quote"
    LIST = "list"
    LIST_ITEM = "list_item"
    CAPTION = "caption"
    TABLE = "table"
    CODE = "code"
    IMAGE = "image"
    SEPARATOR = "separator"
    UNKNOWN = "unknown"


class Asset(BaseModel):
    """A non-text resource (image, stylesheet, font)."""

    model_config = ConfigDict(extra="ignore")

    id: str
    filename: str
    media_type: str
    storage_key: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class TextBlock(BaseModel):
    """A translatable (or preserved) block with stable identity."""

    model_config = ConfigDict(extra="ignore")

    id: str
    type: BlockType = BlockType.PARAGRAPH
    source_order: int
    source_text: str | None = None
    translated_text: str | None = None
    parent_id: str | None = None
    level: int | None = None
    source_ref: str | None = None
    formatting: dict[str, Any] = Field(default_factory=dict)
    attributes: dict[str, Any] = Field(default_factory=dict)
    links: list[str] = Field(default_factory=list)
    style: dict[str, Any] = Field(default_factory=dict)
    placeholders: dict[str, str] = Field(default_factory=dict)

    @property
    def plain_text(self) -> str:
        """Text-only content (markup stripped) for detection/segmentation."""
        plain = self.attributes.get("plain_text")
        if isinstance(plain, str):
            return plain
        return self.source_text or ""

    @property
    def translatable(self) -> bool:
        return self.source_text is not None and bool(self.plain_text.strip())


class Section(BaseModel):
    """A structural section (chapter/part/section)."""

    model_config = ConfigDict(extra="ignore")

    id: str
    source_order: int
    title: str | None = None
    section_type: str | None = None
    source_ref: str | None = None
    parent_id: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    blocks: list[TextBlock] = Field(default_factory=list)
    asset_ids: list[str] = Field(default_factory=list)


class DocumentMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    publisher: str | None = None
    language: str | None = None
    identifier: str | None = None
    description: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class CanonicalDocument(BaseModel):
    """The canonical, serializable document tree."""

    model_config = ConfigDict(extra="ignore")

    canonical_model_version: int = CANONICAL_MODEL_VERSION
    document_id: str | None = None
    source_type: str | None = None
    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)
    source_language: str | None = None
    source_direction: str | None = None
    source_script: str | None = None
    target_language: str | None = None
    target_direction: str | None = None
    sections: list[Section] = Field(default_factory=list)
    assets: list[Asset] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def iter_blocks(self) -> list[TextBlock]:
        return [block for section in self.sections for block in section.blocks]

    def text_blocks(self) -> list[TextBlock]:
        return [block for block in self.iter_blocks() if block.translatable]

    def find_block(self, block_id: str) -> TextBlock | None:
        for block in self.iter_blocks():
            if block.id == block_id:
                return block
        return None

    def find_asset(self, asset_id: str) -> Asset | None:
        for asset in self.assets:
            if asset.id == asset_id:
                return asset
        return None

    def all_block_ids(self) -> list[str]:
        return [block.id for block in self.iter_blocks()]
