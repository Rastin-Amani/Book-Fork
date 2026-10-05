"""Document engine: type detection, storage, canonical persistence."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.documents.adapters.base import DocumentType, ParseOptions
from app.documents.segmentation.base import SegmentationConfig, SegmentationStrategy
from app.documents.service import DocumentEngine
from app.exceptions import ValidationError
from app.storage.local import LocalStorage

from tests.documents_fixtures import write_epub, write_pdf


async def test_detect_type() -> None:
    assert DocumentEngine.detect_type("a.epub", b"PK\x03\x04....") is DocumentType.EPUB
    assert DocumentEngine.detect_type("a.pdf", b"%PDF-1.7") is DocumentType.PDF
    with pytest.raises(ValidationError):
        DocumentEngine.detect_type("a.txt", b"hello")


async def test_parse_and_segment(tmp_path: Path) -> None:
    path = write_epub(tmp_path / "book.epub", chapters=1)
    engine = DocumentEngine()
    result = await engine.parse_file(
        path, document_type=DocumentType.EPUB, options=ParseOptions(document_id="d1")
    )
    segments = engine.segment(
        result.document,
        SegmentationConfig(source_language="en", strategy=SegmentationStrategy.STRUCTURE_AWARE),
    )
    assert segments
    protected = engine.protect(segments)
    assert protected[0].protected.text is not None


async def test_materialize_and_canonical_roundtrip(tmp_path: Path) -> None:
    engine = DocumentEngine(temp_root=tmp_path / "tmp")
    storage = LocalStorage(tmp_path / "store")

    await storage.put("documents/d1/source.epub", b"some-bytes")
    async with engine.materialize(storage, "documents/d1/source.epub") as materialized:
        assert materialized.read_bytes() == b"some-bytes"
    # Cleaned up afterwards.
    assert not materialized.exists()

    parse_result = await engine.parse_file(
        write_epub(tmp_path / "book.epub", chapters=2),
        document_type=DocumentType.EPUB,
        options=ParseOptions(document_id="d1"),
    )
    key = await engine.store_canonical(storage, parse_result.document, document_id="d1")
    assert key == "documents/d1/canonical/v1.json"
    loaded = await engine.load_canonical(storage, key)
    assert len(loaded.sections) == 2


async def test_store_assets(tmp_path: Path) -> None:
    engine = DocumentEngine(temp_root=tmp_path / "tmp")
    storage = LocalStorage(tmp_path / "store")
    result = await engine.parse_file(
        write_epub(tmp_path / "book.epub", chapters=1, with_image=True),
        document_type=DocumentType.EPUB,
        options=ParseOptions(document_id="d1"),
    )
    await engine.store_assets(storage, result, document_id="d1")
    images = [a for a in result.document.assets if a.media_type.startswith("image/")]
    assert images and images[0].storage_key
    assert await storage.exists(images[0].storage_key or "")


async def test_pdf_parse_through_engine(tmp_path: Path) -> None:
    result = await DocumentEngine().parse_file(
        write_pdf(tmp_path / "doc.pdf", pages=2),
        document_type=DocumentType.PDF,
        options=ParseOptions(document_id="d2"),
    )
    assert len(result.document.sections) == 2
