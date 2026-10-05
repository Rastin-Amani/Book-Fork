"""Segmentation interfaces.

Segmentation is structure-aware, not a character-count chop. The strategy is
selected from configuration and considers block type, sentence boundaries and
limits; it always falls back gracefully when sentence detection is uncertain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from app.documents.model import BlockType, CanonicalDocument


class SegmentationStrategy(StrEnum):
    PARAGRAPH = "paragraph"
    SENTENCE = "sentence"
    STRUCTURE_AWARE = "structure_aware"
    CUSTOM = "custom"


@dataclass(frozen=True, slots=True)
class Segment:
    id: str
    block_id: str
    section_id: str
    index: int
    text: str
    source_order: int
    block_type: BlockType
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SegmentationConfig:
    strategy: SegmentationStrategy = SegmentationStrategy.STRUCTURE_AWARE
    max_chars: int = 1200
    batch_size: int | None = None
    context_size: int | None = None
    source_language: str | None = None
    target_language: str | None = None


@runtime_checkable
class Segmenter(Protocol):
    strategy: SegmentationStrategy

    def segment(self, document: CanonicalDocument, config: SegmentationConfig) -> list[Segment]:
        """Return the ordered, stable-id segments for ``document``."""
        ...
