"""PDF extraction and reflowed export."""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest
from app.documents.adapters.base import ExportOptions, ParseOptions
from app.documents.model import BlockType
from app.documents.pdf.exporter import PdfExporter
from app.documents.pdf.parser import PdfParser, _repair_spacing
from app.exceptions import ConfigurationError, ValidationError

from tests.documents_fixtures import write_image_pdf, write_pdf


def _parse(path: Path, **overrides):
    options = ParseOptions(document_id="doc-1", **overrides)
    return PdfParser().parse(path, options)


def _weasyprint_available() -> bool:
    try:
        import weasyprint  # noqa: F401

        return True
    except Exception:
        return False


def test_parses_pages_in_order(tmp_path: Path) -> None:
    path = write_pdf(tmp_path / "doc.pdf", pages=3)
    document = _parse(path).document
    assert len(document.sections) == 3
    assert [section.attributes["page_number"] for section in document.sections] == [1, 2, 3]
    assert document.metadata.title in (None, "")
    text = " ".join(block.plain_text for block in document.text_blocks())
    assert "Body text on page 1" in text


def test_detects_headings(tmp_path: Path) -> None:
    path = write_pdf(tmp_path / "doc.pdf", pages=1, heading=True)
    document = _parse(path).document
    headings = [block for block in document.iter_blocks() if block.type is BlockType.HEADING]
    assert headings
    assert headings[0].level in (1, 2)


def test_block_ids_stable(tmp_path: Path) -> None:
    path = write_pdf(tmp_path / "doc.pdf", pages=2)
    assert _parse(path).document.all_block_ids() == _parse(path).document.all_block_ids()


def test_repairs_glued_words_from_text_layer() -> None:
    assert _repair_spacing("overratedPlanning") == "overrated Planning"
    assert _repair_spacing("TAKEDOWNSIgnore the real world") == "TAKEDOWNS Ignore the real world"
    assert _repair_spacing("FIRSTThe new reality") == "FIRST The new reality"
    assert _repair_spacing("normal text stays") == "normal text stays"


def test_list_markers_are_stripped_typed_and_kept_separate(tmp_path: Path) -> None:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Cover Title", fontname="hebo", fontsize=24)
    y = 110
    for line in ("• First item", "• Second item", "1. Numbered item", "plain paragraph"):
        page.insert_text((72, y), line, fontsize=12)
        y += 22
    second = document.new_page()
    second.insert_text((72, 72), "Chapter One", fontname="hebo", fontsize=24)
    second.insert_text((72, 112), "Bold Subhead", fontname="hebo", fontsize=12)
    second.insert_text((72, 146), "Body text that is not bold at all.", fontsize=12)
    path = tmp_path / "lists.pdf"
    document.save(str(path))
    document.close()

    parsed = _parse(path).document
    items = [b for b in parsed.iter_blocks() if b.type is BlockType.LIST_ITEM]
    assert [b.source_text for b in items] == ["First item", "Second item", "Numbered item"]
    assert items[0].attributes["list_style"] == "unordered"
    assert items[1].attributes["list_style"] == "unordered"
    assert items[2].attributes["list_style"] == "ordered"
    assert items[2].attributes["list_marker"] == "1."

    levels = {b.source_text: b.level for b in parsed.iter_blocks() if b.type is BlockType.HEADING}
    assert levels.get("Chapter One") == 1
    assert levels.get("Bold Subhead") == 2  # size marks the chapters, weight the subheads


def test_bold_line_is_detected_as_heading(tmp_path: Path) -> None:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Ignore the real world", fontname="hebo", fontsize=12)
    page.insert_text(
        (72, 110), "Body text that is plain weight and longer than the title.", fontsize=12
    )
    path = tmp_path / "bold.pdf"
    document.save(str(path))
    document.close()

    parsed = _parse(path).document
    headings = [b.plain_text for b in parsed.iter_blocks() if b.type is BlockType.HEADING]
    assert "Ignore the real world" in headings


def test_first_page_is_captured_as_cover(tmp_path: Path) -> None:
    parsed = _parse(write_pdf(tmp_path / "cover.pdf", pages=2)).document
    covers = [asset for asset in parsed.assets if asset.attributes.get("role") == "cover"]
    assert covers
    assert covers[0].media_type == "image/png"


def test_extracts_image_blocks_in_reading_order(tmp_path: Path) -> None:
    document = _parse(write_image_pdf(tmp_path / "img.pdf")).document
    page_blocks = document.sections[1].blocks
    kinds = [block.type for block in page_blocks]
    assert kinds == [BlockType.PARAGRAPH, BlockType.IMAGE, BlockType.PARAGRAPH]
    image = page_blocks[1]
    assert image.attributes["src"]
    assert 0 < image.attributes["width_pct"] <= 100
    assert image.attributes["align"] in ("left", "center", "right")
    assert image.source_text is None and not image.translatable
    assert any(asset.media_type.startswith("image/") for asset in document.assets)


def test_page_limit(tmp_path: Path) -> None:
    path = write_pdf(tmp_path / "doc.pdf", pages=3)
    with pytest.raises(ValidationError):
        _parse(path, max_pdf_pages=1)


def test_html_export_backend(tmp_path: Path) -> None:
    path = write_pdf(tmp_path / "doc.pdf", pages=2)
    document = _parse(path).document
    for block in document.text_blocks():
        block.translated_text = "متن ترجمه شده"
    export = PdfExporter().export(
        document,
        ExportOptions(
            target_language="fa",
            target_direction="rtl",
            render_backend="html",
            output_dir=tmp_path / "out",
        ),
    )
    assert export.extension == ".html"
    html_text = export.path.read_text(encoding="utf-8")
    assert 'dir="rtl"' in html_text
    assert "متن ترجمه شده" in html_text


def test_unknown_backend_rejected(tmp_path: Path) -> None:
    document = _parse(write_pdf(tmp_path / "doc.pdf", pages=1)).document
    with pytest.raises(ConfigurationError):
        PdfExporter().export(
            document, ExportOptions(render_backend="nonsense", output_dir=tmp_path / "out")
        )


@pytest.mark.skipif(_weasyprint_available(), reason="weasyprint is installed")
def test_weasyprint_backend_reports_missing_dependency(tmp_path: Path) -> None:
    document = _parse(write_pdf(tmp_path / "doc.pdf", pages=1)).document
    with pytest.raises(ConfigurationError):
        PdfExporter().export(
            document, ExportOptions(render_backend="weasyprint", output_dir=tmp_path / "out")
        )
