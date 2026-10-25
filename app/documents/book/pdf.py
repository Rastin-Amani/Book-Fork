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
from app.documents.book.html import block_text, render_body_html, strip_markup
from app.documents.model import BlockType as B
from app.documents.model import CanonicalDocument, Section

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
    media = _page_rect(options.page_size)
    body_doc, toc_entries = _render_body(
        document,
        font=font,
        language=language,
        direction=direction,
        image_src=image_src,
        media=media,
        archive=archive,
        fallback_head=title,
    )
    toc_doc, toc_links = _render_toc(
        toc_entries, font=font, media=media, archive=archive, language=language, direction=direction
    )

    cover_png, generated_cover = _cover_image(document, options, font, title, authors, direction)
    return _assemble(
        cover_png=cover_png,
        generated_cover=generated_cover,
        toc_doc=toc_doc,
        toc_links=toc_links,
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
_MAX_ORPHAN_PASSES = 4


def _render_body(
    document: CanonicalDocument,
    *,
    font: BookFont,
    language: str,
    direction: str,
    image_src: dict[str, str],
    media: pymupdf.Rect,
    archive: pymupdf.Archive,
    fallback_head: str,
) -> tuple[pymupdf.Document, list[TocEntry]]:
    """Lay out the body, keeping headings from being orphaned.

    PyMuPDF's Story engine ignores ``page-break-after/inside: avoid`` (only
    ``always`` is honoured), so a heading that lands at the bottom of a page is
    separated from the text it introduces. We render once, detect headings that
    ended a page, force a page break before them, and repeat until the layout is
    stable. The final pass is the document we keep (it also carries the TOC
    entries and running heads).
    """
    breaks: set[str] = set()
    last_block = _last_block_anchor(document)
    titles = _heading_titles(document)
    doc: pymupdf.Document | None = None
    entries: list[TocEntry] = []
    # ponytail: up to _MAX_ORPHAN_PASSES full layouts; a per-block measuring
    # engine would be one pass, but this needs no reimplementation of Story.
    for _ in range(_MAX_ORPHAN_PASSES):
        body_html = render_body_html(
            document,
            font=font,
            language=language,
            direction=direction,
            image_src=image_src,
            break_before=breaks,
        )
        doc, entries, orphans = _place_body(
            body_html,
            font=font,
            media=media,
            archive=archive,
            fallback_head=fallback_head,
            direction=direction,
            last_block=last_block,
            titles=titles,
        )
        new = {anchor for anchor in orphans if anchor not in breaks}
        if not new:
            return doc, entries
        breaks |= new
    assert doc is not None
    return doc, entries


def _last_block_anchor(document: CanonicalDocument) -> str | None:
    """The anchor of the final rendered block (never force a break before it)."""
    anchors = [
        f"blk-{block.id}" for section in _book_sections(document) for block in section.blocks
    ]
    return anchors[-1] if anchors else None


def _book_sections(document: CanonicalDocument) -> list[Section]:
    """Sections actually rendered (a PDF source's first page is its cover)."""
    return [
        section
        for index, section in enumerate(document.sections)
        if not (document.source_type == "pdf" and index == 0)
    ]


def _heading_titles(document: CanonicalDocument) -> dict[str, str]:
    """Map each heading anchor to its source text.

    ``element_positions`` normalizes the text it reports (it can drop the space
    beside a Latin island), so the TOC and running heads take their labels from
    the canonical model instead.
    """
    titles: dict[str, str] = {}
    for section in _book_sections(document):
        if section.title:
            titles[f"sec-{section.id}"] = strip_markup(section.title)
        for block in section.blocks:
            if block.type is B.HEADING:
                titles[f"blk-{block.id}"] = strip_markup(block_text(block))
    return titles


def _place_body(
    body_html: str,
    *,
    font: BookFont,
    media: pymupdf.Rect,
    archive: pymupdf.Archive,
    fallback_head: str,
    direction: str,
    last_block: str | None,
    titles: dict[str, str],
) -> tuple[pymupdf.Document, list[TocEntry], list[str]]:
    story = pymupdf.Story(html=body_html, archive=archive, user_css=font_face_css(font))
    content = _content_rect(media)
    head_rect = _header_rect(media)
    entries: list[TocEntry] = []
    current = {"head": fallback_head}
    state = {"page": 0, "opened": False}
    placed: list[list[tuple[str, int, float]]] = []

    def record(position: object) -> None:
        if not (getattr(position, "open_close", 0) & 1):
            return
        heading = getattr(position, "heading", 0) or 0
        rect = getattr(position, "rect", (0, 0, 0, 0))
        anchor = getattr(position, "id", "") or ""
        text = titles.get(anchor) or (getattr(position, "text", "") or "")
        if heading > 0:
            entries.append(TocEntry(level=heading, title=text, page=state["page"] + 1, y=rect[1]))
            if heading == 1:
                current["head"] = text
                state["opened"] = True
        while len(placed) <= state["page"]:
            placed.append([])
        placed[state["page"]].append((anchor, heading, float(rect[3])))

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
            head = _running_head(
                current["head"], font=font, archive=archive, size=9, direction=direction
            )
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
    return doc, entries, _orphan_headings(placed, last_block=last_block)


def _orphan_headings(
    placed: list[list[tuple[str, int, float]]], *, last_block: str | None
) -> list[str]:
    """Anchors of headings that ended a page (or split across a page break).

    A heading is orphaned when it is the lowest element placed on its page and
    its text continues elsewhere; forcing a page break before it moves the
    heading to the next page with the text it introduces. The very first page
    and the document's final block are left alone.

    ponytail: bottom-of-page heuristic — no widow/orphan control for ordinary
    paragraphs; add line-level measurement if a real book complains.
    """
    orphans: list[str] = []
    for index, elements in enumerate(placed):
        if not elements or (index == 0 and len(elements) == 1):
            continue
        anchor, heading, _bottom = max(elements, key=lambda item: item[2])
        if heading > 0 and anchor and anchor != last_block and anchor not in orphans:
            orphans.append(anchor)
    return orphans


# -- table of contents -------------------------------------------------------
_TOC_MAX_LEVEL = 2
_TOC_MAX_ENTRIES = 400


def _render_toc(
    entries: list[TocEntry],
    *,
    font: BookFont,
    media: pymupdf.Rect,
    archive: pymupdf.Archive,
    language: str,
    direction: str,
) -> tuple[pymupdf.Document | None, list[tuple[int, pymupdf.Rect, TocEntry]]]:
    visible = _toc_entries(entries)
    if not visible:
        return None, []
    heading = _TOC_TITLES.get(language.split("-", 1)[0].lower(), "Contents")
    rows = "".join(
        f'<tr id="toc-{index}" class="lvl{entry.level}">'
        f'<td class="t">{_escape(entry.title)}</td>'
        f'<td class="p">{entry.page}</td></tr>'
        for index, entry in enumerate(visible)
    )
    html_text = f'<h1 class="toc-title">{_escape(heading)}</h1><table class="toc">{rows}</table>'
    page_number_side = "left" if direction == "rtl" else "right"
    title_side = "right" if direction == "rtl" else "left"
    indent_side = "right" if direction == "rtl" else "left"
    css = (
        font_face_css(font)
        + f"body{{font-family:{font.family_stack()};margin:0;font-size:11pt;"
        + f"direction:{direction};}}"
        + ".toc-title{font-size:20pt;font-weight:bold;margin:0 0 16pt;}"
        # A fixed layout with an explicit number column keeps the page number at
        # the outer edge instead of letting it cling to the title (RTL included).
        + ".toc{table-layout:fixed;width:100%;border-collapse:collapse;}"
        + ".toc td{padding:3pt 0;vertical-align:top;border:0;overflow:hidden;}"
        + f".toc td.t{{border:0;text-align:{title_side};}}"
        + f".toc td.p{{text-align:{page_number_side};width:44pt;}}"
        + f".toc tr.lvl2 td.t{{padding-{indent_side}:18pt;opacity:0.85;}}"
    )
    story = pymupdf.Story(html=html_text, archive=archive, user_css=css)
    links: list[tuple[int, pymupdf.Rect, TocEntry]] = []
    buffer = io.BytesIO()
    writer = pymupdf.DocumentWriter(buffer)
    more = 1
    page_index = 0
    while more:
        device = writer.begin_page(media)
        more, _ = story.place(_content_rect(media))

        def record(position: object, *, _page: int = page_index) -> None:
            if not (getattr(position, "open_close", 0) & 1):
                return
            anchor = getattr(position, "id", "") or ""
            if not anchor.startswith("toc-"):
                return
            index = int(anchor[4:])
            rect = getattr(position, "rect", None)
            if rect and 0 <= index < len(visible):
                links.append((_page, pymupdf.Rect(rect), visible[index]))

        story.element_positions(record)
        story.draw(device)
        writer.end_page()
        page_index += 1
    writer.close()
    return pymupdf.open("pdf", buffer), links


def _toc_entries(entries: list[TocEntry]) -> list[TocEntry]:
    """Keep a readable menu: top levels only, no duplicate titles, bounded size."""
    visible: list[TocEntry] = []
    seen: set[tuple[int, str]] = set()
    for entry in entries:
        if entry.level > _TOC_MAX_LEVEL or not entry.title.strip():
            continue
        key = (entry.level, entry.title)
        if key in seen:
            continue
        seen.add(key)
        visible.append(entry)
        if len(visible) >= _TOC_MAX_ENTRIES:
            break
    return visible


# -- assembly ----------------------------------------------------------------
def _assemble(
    *,
    cover_png: bytes,
    generated_cover: bool,
    toc_doc: pymupdf.Document | None,
    toc_links: list[tuple[int, pymupdf.Rect, TocEntry]],
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
    toc_offset = 1  # the cover occupies page 0
    body_start = out.page_count  # 0-based index of the first body page
    out.insert_pdf(body_doc)

    _number_pages(out, toc_start=toc_offset, toc_count=toc_pages, body_start=body_start)
    if toc_links:
        _link_toc(out, toc_links, toc_offset=toc_offset, body_start=body_start)
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


def _link_toc(
    doc: pymupdf.Document,
    links: list[tuple[int, pymupdf.Rect, TocEntry]],
    *,
    toc_offset: int,
    body_start: int,
) -> None:
    """Make every contents row a jump link (as an annotation, so it stays black).

    The row rectangles are captured while the contents page is laid out, so this
    works for shaped scripts where ``search_for`` cannot find the title.
    """
    for toc_page, rect, entry in links:
        target = body_start + entry.page - 1
        if target >= doc.page_count or target < body_start:
            continue
        doc[toc_page + toc_offset].insert_link(
            {
                "kind": pymupdf.LINK_GOTO,
                "from": rect,
                "to": pymupdf.Point(rect.x0, entry.y),
                "page": target,
            }
        )


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


def _running_head(
    text: str, *, font: BookFont, archive: pymupdf.Archive, size: int, direction: str
) -> pymupdf.Story:
    """The page header as an HTML story so RTL text and parentheses stay correct.

    The low-level paragraph API lays Arabic out in visual order, reversing RTL
    runs and mirroring the mixed Latin islands a converted book's titles
    contain; HTML carries the base direction through to the shaper.
    """
    css = (
        font_face_css(font)
        + f"body{{margin:0;font-family:{font.family_stack()};direction:{direction};}}"
        + f"p{{margin:0;font-size:{size}pt;text-align:center;color:#6e6e6e;}}"
    )
    html_text = f"<html><body><p>{_escape(text)}</p></body></html>"
    return pymupdf.Story(html=html_text, archive=archive, user_css=css)


def _escape(text: str) -> str:
    import html as _html

    return _html.escape(text)


__all__ = ["TocEntry", "render_book_pdf"]
