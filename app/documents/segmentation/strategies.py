"""Segmentation strategies.

``structure_aware`` is the default: it keeps block boundaries and structural
blocks (headings/captions) intact, and only splits long prose by sentence. When
the language is unsupported by the sentence detector, or the block contains
markup, it degrades to paragraph-level segmentation rather than guessing.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from typing import Any

from app.documents.model import BlockType, CanonicalDocument, TextBlock
from app.documents.segmentation.base import (
    Segment,
    SegmentationConfig,
    SegmentationStrategy,
    Segmenter,
)
from app.exceptions import ConfigurationError

Splitter = Callable[[TextBlock], list[str]]

_STRUCTURAL_TYPES = {BlockType.HEADING, BlockType.CAPTION, BlockType.CODE, BlockType.TABLE}
_pysbd_module: Any = None


def _pysbd() -> Any:
    global _pysbd_module
    if _pysbd_module is None:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                import pysbd

            _pysbd_module = pysbd
        except Exception:
            return None
    return _pysbd_module


def sentence_split(text: str, language: str | None) -> list[str] | None:
    """Split ``text`` into sentences, or return None when uncertain/unsupported."""
    module = _pysbd()
    if module is None or not language:
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            segmenter = module.Segmenter(language=language.split("-")[0].lower(), clean=False)
            sentences = [s.strip() for s in segmenter.segment(text) if s.strip()]
    except Exception:
        return None
    return sentences or None


def _has_markup(block: TextBlock) -> bool:
    return "<" in (block.source_text or "")


def _group(sentences: list[str], max_chars: int) -> list[str]:
    segments: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip() if current else sentence
        if current and len(candidate) > max_chars:
            segments.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        segments.append(current)
    return segments


class ParagraphSegmenter:
    strategy = SegmentationStrategy.PARAGRAPH

    def segment(self, document: CanonicalDocument, config: SegmentationConfig) -> list[Segment]:
        return _emit(document, lambda block: [block.plain_text], config)


class SentenceSegmenter:
    strategy = SegmentationStrategy.SENTENCE

    def segment(self, document: CanonicalDocument, config: SegmentationConfig) -> list[Segment]:
        language = config.source_language

        def split(block: TextBlock) -> list[str]:
            if _has_markup(block):
                return [block.plain_text]
            sentences = sentence_split(block.plain_text, language)
            if not sentences:
                return [block.plain_text]
            return _group(sentences, config.max_chars)

        return _emit(document, split, config)


class StructureAwareSegmenter:
    strategy = SegmentationStrategy.STRUCTURE_AWARE

    def segment(self, document: CanonicalDocument, config: SegmentationConfig) -> list[Segment]:
        language = config.source_language

        def split(block: TextBlock) -> list[str]:
            if block.type in _STRUCTURAL_TYPES or _has_markup(block):
                return [block.plain_text]
            if len(block.plain_text) <= config.max_chars:
                return [block.source_text or block.plain_text]
            sentences = sentence_split(block.plain_text, language)
            if not sentences:
                return [block.plain_text]
            # Rebuild sentence groups as plain text when the block had no markup.
            return _group(sentences, config.max_chars)

        return _emit(document, split, config)


def _emit(
    document: CanonicalDocument, splitter: Splitter, config: SegmentationConfig
) -> list[Segment]:
    segments: list[Segment] = []
    order = 0
    for section in document.sections:
        for block in section.blocks:
            if not block.translatable:
                continue
            parts = splitter(block)
            parts = [part for part in parts if part and part.strip()]
            if not parts:
                continue
            for index, part in enumerate(parts):
                segments.append(
                    Segment(
                        id=f"{block.id}#s{index:03d}",
                        block_id=block.id,
                        section_id=section.id,
                        index=index,
                        text=part,
                        source_order=order,
                        block_type=block.type,
                        metadata={"singular": len(parts) == 1},
                    )
                )
                order += 1
    return segments


_SEGMENTERS: dict[SegmentationStrategy, Callable[[], Segmenter]] = {
    SegmentationStrategy.PARAGRAPH: ParagraphSegmenter,
    SegmentationStrategy.SENTENCE: SentenceSegmenter,
    SegmentationStrategy.STRUCTURE_AWARE: StructureAwareSegmenter,
}


def build_segmenter(strategy: SegmentationStrategy | str) -> Segmenter:
    """Construct a segmenter for a configured strategy."""
    try:
        key = SegmentationStrategy(strategy)
    except ValueError as exc:
        raise ConfigurationError(f"Unknown segmentation strategy {strategy!r}.") from exc
    factory = _SEGMENTERS.get(key)
    if factory is None:
        raise ConfigurationError(f"Segmentation strategy {strategy!r} is not implemented.")
    return factory()
