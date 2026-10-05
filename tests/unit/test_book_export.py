"""Book export: fonts, HTML sanitizing, PDF book, EPUB structure."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from app.documents.adapters.base import ExportOptions, ParseOptions
from app.documents.book.fonts import book_font, script_for_language
from app.documents.book.html import directional_paragraphs, render_body_html, sanitize_inline
from app.documents.epub.exporter import EpubExporter
from app.documents.epub.parser import EpubParser
from app.documents.model import (
    BlockType,
    CanonicalDocument,
    DocumentMetadata,
    Section,
    TextBlock,
)
from app.documents.pdf.exporter import PdfExporter

from tests.documents_fixtures import write_epub
from tests.job_fixtures import make_job


def _document(language: str = "fa", direction: str = "rtl") -> CanonicalDocument:
    def block(text: str, bid: str, *, kind: BlockType = BlockType.PARAGRAPH) -> TextBlock:
        return TextBlock(
            id=bid,
            type=kind,
            source_order=0,
            source_text=text,
            translated_text=text,
            attributes={"plain_text": text},
        )

    return CanonicalDocument(
        document_id="doc-1",
        metadata=DocumentMetadata(
            title="بازآرایی" if language == "fa" else "Rework",
            authors=["جیسون فرید"],
            publisher="37signals",
            language=language,
        ),
        sections=[
            Section(
                id="section_000",
                source_order=0,
                title="مقدمه" if language == "fa" else "Introduction",
                blocks=[block("متن نخست", "b1")],
            ),
            Section(
                id="section_001",
                source_order=1,
                title="فصل نخست",
                blocks=[
                    block("متن دوم", "b2"),
                    block("نکته", "b3", kind=BlockType.HEADING),
                ],
            ),
        ],
    )


# -- fonts -------------------------------------------------------------------
def test_font_resolver_picks_script_font() -> None:
    assert book_font("fa").family == "Vazirmatn"
    assert book_font("ar").family == "Vazirmatn"
    assert book_font("en").family == "CrimsonText"
    assert book_font("xx", script="Arab").family == "Vazirmatn"
    assert script_for_language("fa-IR") == "Arab"
    assert script_for_language("en") is None


# -- sanitizing --------------------------------------------------------------
def test_sanitize_inline_drops_scripts_and_keeps_formatting() -> None:
    dirty = '<b>bold</b><script>alert(1)</script><img src="x" onerror="p()"><em>it</em>'
    clean = sanitize_inline(dirty)
    assert "<b>bold</b>" in clean
    assert "<em>it</em>" in clean
    assert "script" not in clean
    assert "onerror" not in clean


def test_render_body_html_is_rtl() -> None:
    html_text = render_body_html(_document(), font=book_font("fa"), language="fa", direction="rtl")
    assert 'style="direction:rtl"' in html_text
    assert "مقدمه" in html_text
    assert "chapter-title" in html_text


def test_render_body_html_keeps_ltr_islands_ltr() -> None:
    document = _document()
    document.sections[0].blocks[0].translated_text = (
        "متن فارسی اینجا است و سپس "
        'Jim Rutenberg, "Clinton Finds Way to Play Along with Drudge," New York Times.'
    )
    html_text = render_body_html(document, font=book_font("fa"), language="fa", direction="rtl")
    assert 'style="direction:rtl"' in html_text
    assert 'style="direction:ltr"' in html_text


def test_directional_paragraphs_split_long_ltr_island() -> None:
    mixed = (
        "متن فارسی اینجا است و سپس "
        'Jim Rutenberg, "Clinton Finds Way to Play Along with Drudge," New York Times.'
    )
    pieces = directional_paragraphs(mixed, "rtl")
    assert [direction for direction, _ in pieces] == ["rtl", "ltr"]


def test_directional_paragraphs_keep_short_island_inline() -> None:
    pieces = directional_paragraphs("ایمیل rework@37signals.com را ببینید", "rtl")
    assert len(pieces) == 1
    assert pieces[0][0] == "rtl"


# -- PDF book ----------------------------------------------------------------
def test_pdf_book_has_cover_toc_outline_and_fonts(tmp_path: Path) -> None:
    import pymupdf

    export = PdfExporter().export(
        _document(),
        ExportOptions(
            target_language="fa",
            target_direction="rtl",
            page_size="a5",
            output_dir=tmp_path / "out",
        ),
    )
    assert export.extension == ".pdf"
    with pymupdf.open(export.path) as doc:
        assert doc.page_count >= 3  # cover + contents + body
        outline = doc.get_toc()
        assert outline and outline[0][1] == "بازآرایی"
        # A generated cover image on the first page.
        assert doc[0].get_images()
        # Book font embedded on body pages.
        body_fonts = {
            font[3] for index in range(1, doc.page_count) for font in doc.get_page_fonts(index)
        }
        assert any("Vazirmatn" in name for name in body_fonts)


def test_html_backend_still_available(tmp_path: Path) -> None:
    export = PdfExporter().export(
        _document(),
        ExportOptions(
            target_language="fa",
            target_direction="rtl",
            render_backend="html",
            output_dir=tmp_path / "out",
        ),
    )
    assert export.extension == ".html"


# -- EPUB --------------------------------------------------------------------
def test_epub_export_has_cover_nav_ncx_and_roundtrips(tmp_path: Path) -> None:
    source = write_epub(tmp_path / "book.epub", chapters=2)
    parsed = EpubParser().parse(source, ParseOptions(document_id="doc-1"))
    document = parsed.document
    for block in document.iter_blocks():
        if block.source_text:
            block.translated_text = block.source_text.replace("Hello", "سلام")

    export = EpubExporter().export(
        document,
        ExportOptions(
            target_language="fa",
            target_direction="rtl",
            output_dir=tmp_path / "out",
            asset_resolver=lambda asset: parsed.asset_bytes.get(asset.id, b""),
        ),
    )
    with zipfile.ZipFile(export.path) as archive:
        names = set(archive.namelist())
        assert "OEBPS/nav.xhtml" in names
        assert "OEBPS/toc.ncx" in names
        assert "OEBPS/cover.xhtml" in names
        assert "OEBPS/cover.png" in names
        assert "OEBPS/styles/book.css" in names
        assert any(name.startswith("OEBPS/fonts/") for name in names)
        opf = archive.read("OEBPS/content.opf").decode("utf-8")
        assert 'properties="cover-image"' in opf
        assert 'page-progression-direction="rtl"' in opf
        assert 'toc="ncx"' in opf
        assert archive.read("OEBPS/cover.png")[:8] == b"\x89PNG\r\n\x1a\n"

    # The cover page and nav are not translatable chapters.
    reparsed = EpubParser().parse(export.path, ParseOptions(document_id="reparsed"))
    assert len(reparsed.document.sections) == len(document.sections)


# -- download selection ------------------------------------------------------
def test_select_output_prefers_requested_then_primary() -> None:
    from app.api.routes.translate import _output_filename, _select_output
    from app.schemas.documents import Document

    job = make_job(
        metadata={
            "outputs": {
                "epub": {"key": "k.epub", "mime": "application/epub+zip", "extension": ".epub"},
                "pdf": {"key": "k.pdf", "mime": "application/pdf", "extension": ".pdf"},
            }
        }
    )
    assert _select_output(job, "pdf")["key"] == "k.pdf"  # type: ignore[index]
    assert _select_output(job, None)["key"] == "k.epub"  # type: ignore[index]
    assert _select_output(job, "azw3")["key"] == "k.epub"  # type: ignore[index]
    assert _select_output(make_job(), None) is None

    document = Document(
        id="d1",
        workspace="w1",
        original_filename="Rework.pdf",
        status="ready",
        created_by="u1",
        document_type="pdf",
    )
    assert _output_filename(document, job, "pdf", "pdf") == "Rework-fa.pdf"
    legacy = make_job(output_storage_key="x.html", output_mime_type="text/html")
    assert _select_output(legacy, None)["key"] == "x.html"  # type: ignore[index]


def test_download_links_opt_out_of_htmx_boost() -> None:
    # The app boosts <body>; a download <a> must not be swapped into the page.
    templates = Path(__file__).resolve().parents[2] / "templates"
    anchor = re.compile(r'<a\b[^>]*href="[^"]*/download[^"]*"[^>]*>')
    checked = 0
    for path in templates.rglob("*.html"):
        for match in anchor.findall(path.read_text(encoding="utf-8")):
            checked += 1
            assert 'hx-boost="false"' in match, f"{path}: {match}"
    assert checked >= 2
