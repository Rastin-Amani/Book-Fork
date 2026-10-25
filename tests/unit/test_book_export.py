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


def test_pdf_toc_rows_are_internal_links(tmp_path: Path) -> None:
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
    with pymupdf.open(export.path) as doc:
        toc_links = doc[1].get_links()  # cover is page 0
        assert toc_links
        assert {link["kind"] for link in toc_links} == {pymupdf.LINK_GOTO}


def test_toc_entries_bounded_deduped_and_top_levels_only() -> None:
    from app.documents.book.pdf import TocEntry, _toc_entries

    duplicates = [TocEntry(level=1, title="Same", page=i, y=0) for i in range(50)]
    assert len(_toc_entries(duplicates)) == 1
    deep = [TocEntry(level=4, title=f"x{i}", page=i, y=0) for i in range(10)]
    assert _toc_entries(deep) == []


def test_render_body_html_emits_break_before() -> None:
    html_text = render_body_html(
        _document(),
        font=book_font("fa"),
        language="fa",
        direction="rtl",
        break_before={"blk-b1"},
    )
    assert "#blk-b1{page-break-before:always;}" in html_text


def test_orphan_headings_detects_only_headings_ending_a_page() -> None:
    from app.documents.book.pdf import _orphan_headings

    placed = [
        [("blk-p1", 0, 100.0), ("blk-h", 2, 500.0)],  # heading at page bottom
        [("blk-f", 0, 60.0)],
    ]
    assert _orphan_headings(placed, last_block="blk-z") == ["blk-h"]
    # a paragraph ending the page is not an orphan
    assert _orphan_headings([[("blk-p", 0, 500.0)]], last_block="blk-z") == []
    # the final block of the book is never forced onto a new page
    assert _orphan_headings([[("blk-h", 1, 500.0)]], last_block="blk-h") == []
    # a heading alone on the very first page stays put
    assert _orphan_headings([[("blk-h", 1, 500.0)]], last_block="blk-z") == []


def _orphan_document(paragraphs: int) -> CanonicalDocument:
    def block(
        text: str, bid: str, *, kind: BlockType = BlockType.PARAGRAPH, level: int | None = None
    ):
        return TextBlock(
            id=bid,
            type=kind,
            source_order=0,
            source_text=text,
            translated_text=text,
            level=level,
            attributes={"plain_text": text},
        )

    blocks = [
        block(f"پاراگراف {i} با متن بیشتر برای پر کردن صفحه و خط.", f"p{i}")
        for i in range(paragraphs)
    ]
    blocks.append(block("UNIQUESUBHEAD", "h", kind=BlockType.HEADING, level=2))
    blocks.append(block("UNIQUEFOLLOWMARKER", "f"))
    blocks.append(block("متن پایانی.", "z"))
    return CanonicalDocument(
        document_id="doc-1",
        metadata=DocumentMetadata(title="تست", language="fa"),
        sections=[Section(id="section_000", source_order=0, title=None, blocks=blocks)],
    )


def test_pdf_heading_is_not_orphaned_on_a_page(tmp_path: Path) -> None:
    import pymupdf

    for paragraphs in (18, 37):
        export = PdfExporter().export(
            _orphan_document(paragraphs),
            ExportOptions(
                target_language="fa",
                target_direction="rtl",
                page_size="a5",
                output_dir=tmp_path / f"out{paragraphs}",
            ),
        )
        with pymupdf.open(export.path) as doc:
            head_page = next(
                (
                    page - 1
                    for _lvl, title, page in doc.get_toc()
                    if title.strip() == "UNIQUESUBHEAD"
                ),
                None,
            )
            follow_page = next(
                (i for i in range(doc.page_count) if "UNIQUEFOLLOWMARKER" in doc[i].get_text()),
                None,
            )
            assert head_page is not None and follow_page is not None
            assert head_page == follow_page


def test_pdf_rtl_list_bullet_sits_on_the_right(tmp_path: Path) -> None:
    import pymupdf

    block = TextBlock(
        id="li1",
        type=BlockType.LIST_ITEM,
        source_order=0,
        source_text="آیتم فهرست",
        translated_text="آیتم فهرست",
        attributes={"plain_text": "آیتم فهرست", "list_style": "unordered"},
    )
    document = CanonicalDocument(
        document_id="doc-1",
        metadata=DocumentMetadata(title="تست", language="fa"),
        sections=[Section(id="section_000", source_order=0, title="فصل", blocks=[block])],
    )
    export = PdfExporter().export(
        document,
        ExportOptions(
            target_language="fa",
            target_direction="rtl",
            page_size="a5",
            output_dir=tmp_path / "out",
        ),
    )
    with pymupdf.open(export.path) as doc:
        found = [rect for page in doc for rect in page.search_for("•")]
        assert found
        midpoint = doc[0].rect.width / 2
        assert all(rect.x0 > midpoint for rect in found)


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


def test_epub_groups_pdf_list_items_into_a_real_list(tmp_path: Path) -> None:
    items = [
        TextBlock(
            id=f"li{index}",
            type=BlockType.LIST_ITEM,
            source_order=index,
            source_text=text,
            translated_text=text,
            attributes={"plain_text": text, "list_style": "unordered"},
        )
        for index, text in enumerate(("آیتم یک", "آیتم دو"))
    ]
    document = CanonicalDocument(
        document_id="doc-1",
        source_type="pdf",
        metadata=DocumentMetadata(title="کتاب", language="fa"),
        sections=[Section(id="section_000", source_order=0, title="فصل", blocks=items)],
    )
    export = EpubExporter().export(
        document,
        ExportOptions(target_language="fa", target_direction="rtl", output_dir=tmp_path / "out"),
    )
    with zipfile.ZipFile(export.path) as archive:
        chapter = next(
            name
            for name in archive.namelist()
            if name.endswith(".xhtml") and "cover" not in name and "nav" not in name
        )
        xhtml = archive.read(chapter).decode("utf-8")
    assert "<ul>" in xhtml
    assert xhtml.count("<li ") == 2
    assert "<body><li" not in xhtml


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
