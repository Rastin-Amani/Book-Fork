"""Generated book cover.

A cover image (PNG) is rendered through PyMuPDF's ``Story`` engine so complex
scripts (Arabic/Persian) are shaped and reordered correctly, then composited
over a drawn background. The same image is used as the PDF cover page and as the
EPUB cover (which Kindle/Apple Books show in the library).

Text is laid out centered so the cover reads correctly for both LTR and RTL
books, and it uses the Story DOM API (not CSS alignment) which is stable across
PyMuPDF versions.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import pymupdf

from app.documents.book.fonts import BookFont, font_face_css

# A portrait 2:3 cover, large enough for Kindle/Apple Books thumbnails.
COVER_WIDTH = 1600
COVER_HEIGHT = 2400

_MARGIN = 120
# ``set_color`` takes 0-255 components (unlike drawing calls which take 0-1).
_INK = (245, 241, 230)
_SUBINK = (230, 226, 214)
_GOLD = (184, 158, 97)
_BG = (0.07, 0.09, 0.14)
_BAND = (0.10, 0.13, 0.20)
_RULE = (0.72, 0.62, 0.38)


@dataclass(frozen=True, slots=True)
class CoverSpec:
    title: str
    authors: tuple[str, ...] = ()
    publisher: str | None = None
    language_name: str | None = None
    direction: str = "ltr"


def render_cover_png(spec: CoverSpec, font: BookFont) -> bytes:
    """Render a printable book cover as PNG bytes."""
    text_pdf = _render_cover_text(spec, font)
    doc = pymupdf.open()
    page = doc.new_page(width=COVER_WIDTH, height=COVER_HEIGHT)
    page.draw_rect(page.rect, color=None, fill=_BG, width=0)
    band = pymupdf.Rect(0, COVER_HEIGHT * 0.30, COVER_WIDTH, COVER_HEIGHT * 0.68)
    page.draw_rect(band, color=None, fill=_BAND, width=0)
    page.draw_rect(
        pymupdf.Rect(_MARGIN, _MARGIN, COVER_WIDTH - _MARGIN, COVER_HEIGHT - _MARGIN),
        color=_RULE,
        width=6,
    )
    if spec.authors:
        y = COVER_HEIGHT * 0.665
        page.draw_line(
            pymupdf.Point(COVER_WIDTH * 0.25, y),
            pymupdf.Point(COVER_WIDTH * 0.75, y),
            color=_RULE,
            width=3,
        )
    page.show_pdf_page(page.rect, text_pdf, 0)
    pixmap = page.get_pixmap(alpha=False)
    data = pixmap.tobytes("png")
    text_pdf.close()
    doc.close()
    return data


def _render_cover_text(spec: CoverSpec, font: BookFont) -> pymupdf.Document:
    css = font_face_css(font)
    authors = "، ".join(spec.authors) if spec.direction == "rtl" else ", ".join(spec.authors)
    footer = " · ".join(part for part in (spec.publisher, spec.language_name) if part)

    placements: list[tuple[str, float, float, int, bool, tuple[int, int, int]]] = [
        (spec.title, 0.30, 0.68, 92, True, _INK),
    ]
    if authors:
        placements.append((authors, 0.69, 0.80, 52, False, _SUBINK))
    if footer:
        placements.append((footer, 0.86, 0.94, 38, False, _GOLD))

    buffer = io.BytesIO()
    writer = pymupdf.DocumentWriter(buffer)
    mediabox = pymupdf.Rect(0, 0, COVER_WIDTH, COVER_HEIGHT)
    device = writer.begin_page(mediabox)
    for text, top, bottom, size, bold, color in placements:
        story = _story(text, font=font, css=css, size=size, bold=bold, color=color)
        rect = pymupdf.Rect(
            _MARGIN + 40, COVER_HEIGHT * top, COVER_WIDTH - _MARGIN - 40, COVER_HEIGHT * bottom
        )
        story.place(rect)
        story.draw(device)
    writer.end_page()
    writer.close()
    return pymupdf.open("pdf", buffer)


def _story(
    text: str,
    *,
    font: BookFont,
    css: str,
    size: int,
    bold: bool,
    color: tuple[int, int, int],
) -> pymupdf.Story:
    story = pymupdf.Story(archive=pymupdf.Archive(str(font.regular.parent)), user_css=css)
    body = story.body
    body.set_properties(font=font.family)
    paragraph = body.add_paragraph()
    paragraph.set_align(pymupdf.TEXT_ALIGN_CENTER)
    paragraph.set_font(font.family)
    paragraph.set_bold(bold)
    paragraph.set_fontsize(size)
    paragraph.set_color(color)
    paragraph.add_text(text)
    return story


__all__ = ["COVER_HEIGHT", "COVER_WIDTH", "CoverSpec", "render_cover_png"]
