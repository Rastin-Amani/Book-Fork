"""Structure-aware segmentation strategies."""

from __future__ import annotations

from app.documents.model import (
    BlockType,
    CanonicalDocument,
    Section,
    TextBlock,
)
from app.documents.segmentation.base import SegmentationConfig, SegmentationStrategy
from app.documents.segmentation.strategies import build_segmenter, sentence_split


def _document() -> CanonicalDocument:
    long_paragraph = (
        "This is the first sentence of a long paragraph. "
        "This is the second sentence with more detail. "
        "And a third sentence to force splitting."
    )
    return CanonicalDocument(
        sections=[
            Section(
                id="section_000",
                source_order=0,
                blocks=[
                    TextBlock(
                        id="block_0000",
                        type=BlockType.HEADING,
                        source_order=0,
                        source_text="A Heading",
                        attributes={"plain_text": "A Heading"},
                    ),
                    TextBlock(
                        id="block_0001",
                        type=BlockType.PARAGRAPH,
                        source_order=1,
                        source_text=long_paragraph,
                        attributes={"plain_text": long_paragraph},
                    ),
                    TextBlock(
                        id="block_0002",
                        type=BlockType.PARAGRAPH,
                        source_order=2,
                        source_text="Inline <em>markup</em> here.",
                        attributes={"plain_text": "Inline markup here."},
                    ),
                ],
            )
        ]
    )


def test_paragraph_strategy_one_per_block() -> None:
    segments = build_segmenter(SegmentationStrategy.PARAGRAPH).segment(
        _document(), SegmentationConfig()
    )
    assert [segment.block_id for segment in segments] == [
        "block_0000",
        "block_0001",
        "block_0002",
    ]


def test_ids_are_stable_and_unique() -> None:
    segments = build_segmenter(SegmentationStrategy.SENTENCE).segment(
        _document(), SegmentationConfig(source_language="en", max_chars=60)
    )
    ids = [segment.id for segment in segments]
    assert len(ids) == len(set(ids))
    assert ids[0].startswith("block_0000#s")


def test_sentence_strategy_splits_language_aware() -> None:
    segments = build_segmenter(SegmentationStrategy.SENTENCE).segment(
        _document(), SegmentationConfig(source_language="en", max_chars=60)
    )
    # The long paragraph must split into more than one segment.
    paragraph_segments = [s for s in segments if s.block_id == "block_0001"]
    assert len(paragraph_segments) > 1


def test_unsupported_language_falls_back_to_paragraph() -> None:
    assert sentence_split("Some text. More text.", "xx") is None


def test_structure_aware_keeps_headings_whole_and_markup_whole() -> None:
    segments = build_segmenter(SegmentationStrategy.STRUCTURE_AWARE).segment(
        _document(), SegmentationConfig(source_language="en", max_chars=10)
    )
    heading = [s for s in segments if s.block_id == "block_0000"]
    assert len(heading) == 1
    markup = [s for s in segments if s.block_id == "block_0002"]
    assert len(markup) == 1
    assert "markup" in markup[0].text


def test_persian_sentence_split_works() -> None:
    text = "این جمله اول است. این جمله دوم است. و این جمله سوم است."
    sentences = sentence_split(text, "fa")
    assert sentences is not None and len(sentences) >= 2


def test_metadata_marks_singular_segments() -> None:
    segments = build_segmenter(SegmentationStrategy.STRUCTURE_AWARE).segment(
        _document(), SegmentationConfig(source_language="en")
    )
    heading = next(s for s in segments if s.block_id == "block_0000")
    assert heading.metadata["singular"] is True
