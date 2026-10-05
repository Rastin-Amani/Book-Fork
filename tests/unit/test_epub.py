"""EPUB parsing and reconstruction."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from app.documents.adapters.base import ExportOptions, ParseOptions
from app.documents.epub.exporter import EpubExporter
from app.documents.epub.parser import EpubParser
from app.documents.model import BlockType
from app.exceptions import DocumentCorruptedError, ValidationError

from tests.documents_fixtures import (
    write_epub,
    write_malformed_epub,
    write_traversal_zip,
)


def _parse(path: Path, *, document_id: str = "doc-1"):
    return EpubParser().parse(path, ParseOptions(document_id=document_id))


def test_parses_structure_and_metadata(tmp_path: Path) -> None:
    path = write_epub(tmp_path / "book.epub", chapters=2)
    result = _parse(path)
    document = result.document
    assert len(document.sections) == 2
    assert document.metadata.title == "Test Book"
    assert document.metadata.authors == ["Ada Lovelace"]
    types = {block.type for block in document.text_blocks()}
    assert {BlockType.HEADING, BlockType.PARAGRAPH, BlockType.LIST_ITEM, BlockType.QUOTE} <= types
    assert BlockType.LIST in {block.type for block in document.iter_blocks()}


def test_preserves_inline_markup_and_links(tmp_path: Path) -> None:
    path = write_epub(tmp_path / "book.epub", chapters=1)
    document = _parse(path).document
    paragraph = next(
        block for block in document.text_blocks() if "world" in (block.source_text or "")
    )
    assert "<em" in (paragraph.source_text or "")
    linked = next(block for block in document.text_blocks() if block.links)
    assert "https://example.com/page" in linked.links


def test_block_ids_are_stable_across_parses(tmp_path: Path) -> None:
    path = write_epub(tmp_path / "book.epub", chapters=2)
    first = _parse(path).document.all_block_ids()
    second = _parse(path).document.all_block_ids()
    assert first == second
    assert first[0] == "block_0000"


def test_images_are_captured(tmp_path: Path) -> None:
    path = write_epub(tmp_path / "book.epub", chapters=1, with_image=True)
    result = _parse(path)
    images = [asset for asset in result.document.assets if asset.media_type.startswith("image/")]
    assert images
    assert result.asset_bytes[images[0].id][:8] == b"\x89PNG\r\n\x1a\n"


def test_invalid_epubs_rejected(tmp_path: Path) -> None:
    bad_mime = write_epub(tmp_path / "badmime.epub", bad_mimetype=True)
    with pytest.raises(DocumentCorruptedError):
        _parse(bad_mime)
    missing = write_epub(tmp_path / "nomime.epub", missing_mimetype=True)
    with pytest.raises(DocumentCorruptedError):
        _parse(missing)
    malformed = write_malformed_epub(tmp_path / "broken.epub")
    with pytest.raises(DocumentCorruptedError):
        _parse(malformed)
    traversal = write_traversal_zip(tmp_path / "evil.epub")
    with pytest.raises(ValidationError):
        _parse(traversal)


def test_export_produces_valid_epub(tmp_path: Path) -> None:
    path = write_epub(tmp_path / "book.epub", chapters=2, with_image=True)
    result = _parse(path)
    document = result.document
    for block in document.iter_blocks():
        if block.source_text:
            block.translated_text = block.source_text.replace("Hello", "سلام")

    output_dir = tmp_path / "out"
    export = EpubExporter().export(
        document,
        ExportOptions(
            target_language="fa",
            target_direction="rtl",
            output_dir=output_dir,
            asset_resolver=lambda asset: result.asset_bytes.get(asset.id),
        ),
    )
    assert export.extension == ".epub"

    with zipfile.ZipFile(export.path) as archive:
        names = archive.namelist()
        assert names[0] == "mimetype"
        assert archive.infolist()[0].compress_type == zipfile.ZIP_STORED
        assert archive.read("mimetype") == b"application/epub+zip"
        assert "OEBPS/content.opf" in names
        chapter = archive.read("OEBPS/section_000.xhtml").decode("utf-8")
        assert 'dir="rtl"' in chapter
        assert 'lang="fa"' in chapter
        assert "سلام" in chapter
        assert any(name.startswith("OEBPS/assets/") for name in names)


def test_exported_epub_reparses(tmp_path: Path) -> None:
    path = write_epub(tmp_path / "book.epub", chapters=2)
    document = _parse(path).document
    export = EpubExporter().export(document, ExportOptions(output_dir=tmp_path / "out"))
    reparsed = _parse(export.path, document_id="reparsed")
    assert len(reparsed.document.sections) == len(document.sections)
    assert reparsed.document.metadata.title == "Test Book"


def test_cover_image_is_detected_and_exported(tmp_path: Path) -> None:
    path = write_epub(tmp_path / "cover.epub", chapters=1, with_cover=True)
    result = _parse(path)
    document = result.document
    covers = [asset for asset in document.assets if asset.attributes.get("role") == "cover"]
    assert covers
    export = EpubExporter().export(
        document,
        ExportOptions(
            target_language="fa",
            target_direction="rtl",
            output_dir=tmp_path / "out",
            asset_resolver=lambda asset: result.asset_bytes.get(asset.id, b""),
        ),
    )
    with zipfile.ZipFile(export.path) as archive:
        names = archive.namelist()
        assert "OEBPS/cover.png" in names
        # The cover is not duplicated under assets/.
        assert not any(name.startswith("OEBPS/assets/") and "cover" in name for name in names)
        opf = archive.read("OEBPS/content.opf").decode("utf-8")
        assert 'href="cover.png"' in opf
