"""Print-ready PDF book rendering via PyMuPDF's Story engine.

Produces a real book: a generated cover, a table of contents with printed page
numbers, running heads, page numbers, and a PDF outline (bookmarks) plus
clickable TOC entries. Pure Python — no system libraries — and RTL-aware, so
Persian/Arabic books shape and lay out correctly.

Front matter (cover, contents) is unnumbered; body pages are numbered 1..N, so
the contents' page references are stable regardless of how many contents pages
the book needs.
"""

from __future__ import annotations

import contextlib
import io
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from app.documents.adapters.base import ExportOptions
from app.documents.book.cover import CoverSpec, render_cover_png
from app.documents.book.fonts import BookFont, book_font, font_face_css
from app.documents.book.html import render_body_html
from app.documents.model import CanonicalDocument

_PAGE_SIZES = {"a4": "a4", "a5": "a5", "b5": "b5", "letter": "letter", "legal": "legal", "a6": "a6"}
_MARGIN = 45
_HEADER_TOP = 24
_CONTENT_TOP = 58
_CONTENT_BOTTOM = 52

_TOC_TITLES = {
    "fa": "فهرست",
    "ar": "المحتويات",
    "ur": "فہرست",
    "he": "תוכן העניינים",
    "ps": "منځپانګه",
}


@dataclass(frozen=True, slots=True)
class TocEntry:
    level: int
    title: str
    page: int  # 1-based body page
    y: float


def render_book_pdf(document: CanonicalDocument, options: ExportOptions) -> bytes:
    language = options.target_language or document.metadata.language or "und"
    direction = "rtl" if options.target_direction == "rtl" else "ltr"
    font = book_font(language, script=options.target_script, font_dir=options.font_dir)
    title = options.document_title or document.metadata.title or "Translated document"
    authors = tuple(a for a in document.metadata.authors if a)

    archive, image_src = _build_archive(document, font, options)
    body_html = render_body_html(
        document, font=font, language=language, direction=direction, image_src=image_src
    )
    media = _page_rect(options.page_size)
    body_doc, toc_entries = _render_body(
        body_html, font=font, media=media, archive=archive, fallback_head=title
    )
    toc_doc = _render_toc(
        toc_entries, font=font, media=media, archive=archive, language=language, direction=direction
    )

    cover_png, generated_cover = _cover_image(document, options, font, title, authors, direction)
    return _assemble(
        cover_png=cover_png,
        generated_cover=generated_cover,
        toc_doc=toc_doc,
        toc_entries=toc_entries,
        body_doc=body_doc,
        media=media,
        title=title,
        authors=authors,
        language=language,
        direction=direction,
    )


def _cover_image(
    document: CanonicalDocument,
    options: ExportOptions,
    font: BookFont,
    title: str,
    authors: tuple[str, ...],
    direction: str,
) -> tuple[bytes, bool]:
    """Use the document's own cover when present, else generate one."""
    resolver = options.asset_resolver
    if resolver is not None:
        for asset in document.assets:
            if asset.attributes.get("role") != "cover" or not asset.media_type.startswith("image/"):
                continue
            try:
                data = resolver(asset)
            except Exception:
                data = None
            if data:
                return data, False
    return (
        render_cover_png(
            CoverSpec(
                title=title,
                authors=authors,
                publisher=document.metadata.publisher,
                language_name=None,
                direction=direction,
            ),
            font,
        ),
        True,
    )


# -- archive & assets --------------------------------------------------------
def _build_archive(
    document: CanonicalDocument, font: BookFont, options: ExportOptions
) -> tuple[pymupdf.Archive, dict[str, str]]:
    archive = pymupdf.Archive(str(font.regular.parent))
    image_src: dict[str, str] = {}
    resolver = options.asset_resolver
    if resolver is None:
        return archive, image_src
    assets_by_name = {
        Path(asset.filename).name: asset
        for asset in document.assets
        if asset.media_type.startswith("image/")
    }
    for block in document.iter_blocks():
        if block.type.value != "image":
            continue
        src = str(block.attributes.get("src") or "")
        asset = assets_by_name.get(Path(src).name)
        if asset is None:
            continue
        try:
            data = resolver(asset)
        except Exception:  # noqa: S112 - a missing image must not fail the book
            continue
        if not data:
            continue
        name = f"assets/{asset.id}/{Path(asset.filename).name}"
        archive.add(data, name)
        image_src[block.id] = name
    return archive, image_src


# -- body --------------------------------------------------------------------
def _render_body(
    body_html: str,
    *,
    font: BookFont,
    media: pymupdf.Rect,
    archive: pymupdf.Archive,
    fallback_head: str,
) -> tuple[pymupdf.Document, list[TocEntry]]:
    story = pymupdf.Story(html=body_html, archive=archive, user_css=font_face_css(font))
    content = _content_rect(media)
    head_rect = _header_rect(media)
    entries: list[TocEntry] = []
    current = {"head": fallback_head}
    state = {"page": 0, "opened": False}

    def record(position: object) -> None:
        if not (getattr(position, "open_close", 0) & 1):
            return
        heading = getattr(position, "heading", 0) or 0
        text = getattr(position, "text", "") or ""
        if heading > 0:
            rect = getattr(position, "rect", (0, 0, 0, 0))
            entries.append(TocEntry(level=heading, title=text, page=state["page"] + 1, y=rect[1]))
            if heading == 1:
                current["head"] = text
                state["opened"] = True

    buffer = io.BytesIO()
    writer = pymupdf.DocumentWriter(buffer)
    more = 1
    page = 0
    while more:
        state["page"] = page
        state["opened"] = False
        device = writer.begin_page(media)
        more, _ = story.place(content)
        story.element_positions(record)
        story.draw(device)
        if not state["opened"]:
            head = _text_story(current["head"], font=font, archive=archive, size=9)
            head.place(head_rect)
            head.draw(device)
        writer.end_page()
        page += 1
        if page > 20000:  # safety: never spin forever on malformed content
            break
    writer.close()
    doc = pymupdf.open("pdf", buffer)
    if doc.page_count == 0:
        doc.new_page(width=media.width, height=media.height)
    return doc, entries


# -- table of contents -------------------------------------------------------
def _render_toc(
    entries: list[TocEntry],
    *,
    font: BookFont,
    media: pymupdf.Rect,
    archive: pymupdf.Archive,
    language: str,
    direction: str,
) -> pymupdf.Document | None:
    if not entries:
        return None
    heading = _TOC_TITLES.get(language.split("-", 1)[0].lower(), "Contents")
    rows = "".join(
        f'<tr class="lvl{entry.level}"><td class="t">{_escape(entry.title)}</td>'
        f'<td class="p">{entry.page}</td></tr>'
        for entry in entries
        if entry.level <= 3
    )
    html_text = f'<h1 class="toc-title">{_escape(heading)}</h1><table class="toc">{rows}</table>'
    page_number_side = "left" if direction == "rtl" else "right"
    css = (
        font_face_css(font)
        + f"body{{font-family:{font.family_stack()};margin:0;font-size:11pt;"
        + f"direction:{direction};}}"
        + ".toc-title{font-size:20pt;font-weight:bold;margin:0 0 16pt;}"
        + ".toc{width:100%;border-collapse:collapse;}"
        + ".toc td{padding:3pt 0;vertical-align:top;border:0;}"
        + ".toc td.t{border:0;}"
        + f".toc td.p{{text-align:{page_number_side};width:12%;}}"
        + ".toc tr.lvl2 td.t{padding-left:18pt;padding-right:18pt;opacity:0.85;}"
        + ".toc tr.lvl3 td.t{padding-left:36pt;padding-right:36pt;opacity:0.75;}"
    )
    story = pymupdf.Story(html=html_text, archive=archive, user_css=css)
    buffer = io.BytesIO()
    writer = pymupdf.DocumentWriter(buffer)
    more = 1
    while more:
        device = writer.begin_page(media)
        more, _ = story.place(_content_rect(media))
        story.draw(device)
        writer.end_page()
    writer.close()
    return pymupdf.open("pdf", buffer)


# -- assembly ----------------------------------------------------------------
def _assemble(
    *,
    cover_png: bytes,
    generated_cover: bool,
    toc_doc: pymupdf.Document | None,
    toc_entries: list[TocEntry],
    body_doc: pymupdf.Document,
    media: pymupdf.Rect,
    title: str,
    authors: tuple[str, ...],
    language: str,
    direction: str,
) -> bytes:
    out = pymupdf.open()
    cover = out.new_page(width=media.width, height=media.height)
    background = (0.07, 0.09, 0.14) if generated_cover else (1, 1, 1)
    cover.draw_rect(cover.rect, color=None, fill=background, width=0)
    cover.insert_image(cover.rect, stream=cover_png, keep_proportion=True)

    toc_pages = toc_doc.page_count if toc_doc is not None else 0
    if toc_doc is not None:
        out.insert_pdf(toc_doc)
    body_start = out.page_count  # 0-based index of the first body page
    out.insert_pdf(body_doc)

    _number_pages(out, toc_start=1, toc_count=toc_pages, body_start=body_start)
    if toc_doc is not None:
        _link_toc(out, toc_entries, body_start=body_start)
    _set_outline(out, toc_entries, body_start=body_start, title=title)
    _set_language(out, language, direction)

    out.set_metadata(
        {
            "title": title,
            "author": ", ".join(authors),
            "creator": "Book Fork",
            "producer": "Book Fork",
        }
    )
    data = out.tobytes(deflate=True, garbage=3)
    out.close()
    return data


def _set_language(doc: pymupdf.Document, language: str, direction: str) -> None:
    """Tag the PDF language and reading direction for viewers/screen readers."""
    with contextlib.suppress(Exception):
        catalog = doc.pdf_catalog()
        doc.xref_set_key(catalog, "Lang", f"({language})")
    if direction == "rtl":
        with contextlib.suppress(Exception):
            doc.xref_set_key(doc.pdf_catalog(), "ViewerPreferences", "<< /Direction /R2L >>")


def _number_pages(
    doc: pymupdf.Document, *, toc_start: int, toc_count: int, body_start: int
) -> None:
    media = doc[0].rect
    align = pymupdf.TEXT_ALIGN_CENTER
    roman = _roman
    for index in range(toc_start, toc_start + toc_count):
        label = roman(index - toc_start + 1)
        doc[index].insert_textbox(
            _footer_rect(media),
            label,
            fontname="times-roman",
            fontsize=9,
            align=align,
            color=(0.3, 0.3, 0.3),
        )
    page = 1
    for index in range(body_start, doc.page_count):
        doc[index].insert_textbox(
            _footer_rect(media), str(page), fontname="times-roman", fontsize=9.5, align=align
        )
        page += 1


def _link_toc(doc: pymupdf.Document, entries: list[TocEntry], *, body_start: int) -> None:
    toc_pages = range(1, body_start)
    for entry in entries:
        if entry.level > 3 or not entry.title:
            continue
        target = body_start + entry.page - 1
        if target >= doc.page_count:
            continue
        for index in toc_pages:
            page = doc[index]
            found = page.search_for(entry.title)
            if not found:
                continue
            for rect in found:
                page.insert_link(
                    {
                        "kind": pymupdf.LINK_GOTO,
                        "from": rect,
                        "to": pymupdf.Point(0, entry.y),
                        "page": target,
                    }
                )
            break


def _set_outline(
    doc: pymupdf.Document, entries: list[TocEntry], *, body_start: int, title: str
) -> None:
    outline: list[list[object]] = [[1, title, 1]]
    for entry in entries:
        if entry.level > 3:
            continue
        page = body_start + entry.page  # set_toc is 1-based absolute
        outline.append([entry.level, entry.title or f"Page {entry.page}", page])
    with contextlib.suppress(Exception):  # outline is best-effort
        doc.set_toc(outline)


# -- geometry / helpers ------------------------------------------------------
def _page_rect(size: str) -> pymupdf.Rect:
    name = _PAGE_SIZES.get(size.lower(), "a5")
    return pymupdf.paper_rect(name)


def _content_rect(media: pymupdf.Rect) -> pymupdf.Rect:
    return pymupdf.Rect(
        media.x0 + _MARGIN,
        media.y0 + _CONTENT_TOP,
        media.x1 - _MARGIN,
        media.y1 - _CONTENT_BOTTOM,
    )


def _header_rect(media: pymupdf.Rect) -> pymupdf.Rect:
    return pymupdf.Rect(
        media.x0 + _MARGIN,
        media.y0 + _HEADER_TOP,
        media.x1 - _MARGIN,
        media.y0 + _CONTENT_TOP - 6,
    )


def _footer_rect(media: pymupdf.Rect) -> pymupdf.Rect:
    return pymupdf.Rect(
        media.x0 + _MARGIN,
        media.y1 - _CONTENT_BOTTOM + 10,
        media.x1 - _MARGIN,
        media.y1 - 16,
    )


_INT_TO_ROMAN = [
    (1000, "m"),
    (900, "cm"),
    (500, "d"),
    (400, "cd"),
    (100, "c"),
    (90, "xc"),
    (50, "l"),
    (40, "xl"),
    (10, "x"),
    (9, "ix"),
    (5, "v"),
    (4, "iv"),
    (1, "i"),
]


def _roman(value: int) -> str:
    result = ""
    for number, numeral in _INT_TO_ROMAN:
        while value >= number:
            result += numeral
            value -= number
    return result


def _text_story(text: str, *, font: BookFont, archive: pymupdf.Archive, size: int) -> pymupdf.Story:
    story = pymupdf.Story(archive=archive, user_css=font_face_css(font))
    paragraph = story.body.add_paragraph()
    paragraph.set_align(pymupdf.TEXT_ALIGN_CENTER)
    paragraph.set_font(font.family)
    paragraph.set_fontsize(size)
    paragraph.set_color((110, 110, 110))
    paragraph.add_text(text)
    return story


def _escape(text: str) -> str:
    import html as _html

    return _html.escape(text)


__all__ = ["TocEntry", "render_book_pdf"]
