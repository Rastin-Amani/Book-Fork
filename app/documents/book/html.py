"""Book HTML generation from the canonical model.

Used by the PDF renderer. Inline markup from source EPUBs is sanitized to a
small whitelist before it reaches the renderer, so untrusted input can never
inject scripts, styles or event handlers. Text direction is applied from the
target language so RTL books lay out and print correctly.
"""

from __future__ import annotations

import html
import re
from collections.abc import Mapping, Sequence

from lxml import etree

from app.documents.book.fonts import BookFont, font_face_css
from app.documents.model import BlockType as B
from app.documents.model import CanonicalDocument, Section, TextBlock

XHTML_NS = "http://www.w3.org/1999/xhtml"
_XHTML = etree.XMLParser(recover=True, resolve_entities=False, load_dtd=False, no_network=True)

_ALLOWED_TAGS = {
    "a",
    "b",
    "strong",
    "i",
    "em",
    "u",
    "s",
    "strike",
    "del",
    "ins",
    "mark",
    "small",
    "sub",
    "sup",
    "code",
    "kbd",
    "samp",
    "var",
    "br",
    "span",
    "abbr",
    "q",
    "cite",
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "td",
    "th",
    "caption",
    "img",
}
_VOID_TAGS = {"br", "img"}
_ALLOWED_ATTRS = {
    "href",
    "id",
    "class",
    "dir",
    "lang",
    "src",
    "alt",
    "colspan",
    "rowspan",
    "scope",
    "title",
}
_SAFE_URL_PREFIXES = ("http://", "https://", "mailto:", "#", "/", "./", "../")
_TAG = re.compile(r"<[^>]+>")


def strip_markup(markup: str | None) -> str:
    """Plain text for direction detection (inline tags removed)."""
    return _TAG.sub("", markup) if markup else ""


def text_direction(text: str, default: str = "ltr") -> str:
    """Base direction for a run of text from its dominant script.

    RTL books contain LTR islands (English citations, URLs, product names).
    Choosing direction per block keeps each readable instead of forcing one
    direction on the whole book. Mixed blocks follow whichever script has more
    letters; letterless blocks (numbers, punctuation) inherit ``default``.
    """
    rtl = sum(1 for char in text if "\u0590" <= char <= "\u08ff" or "\ufb1d" <= char <= "\ufeff")
    ltr = sum(1 for char in text if char.isascii() and char.isalpha())
    if rtl > ltr:
        return "rtl"
    if ltr > rtl:
        return "ltr"
    return default


def _char_class(char: str) -> str | None:
    if "\u0590" <= char <= "\u08ff" or "\ufb1d" <= char <= "\ufeff":
        return "rtl"
    if char.isascii() and char.isalpha():
        return "ltr"
    return None


def _script_runs(text: str) -> list[tuple[str | None, str]]:
    """Text split into maximal runs of one strong script.

    Neutral characters (spaces, punctuation, digits) stay with the run they
    follow so a Latin phrase like ``Jim Rutenberg, "Clinton…`` is one run, not a
    run per word.
    """
    runs: list[str] = []
    classes: list[str | None] = []
    for char in text:
        cls = _char_class(char)
        if not runs:
            classes.append(cls)
            runs.append(char)
            continue
        last = classes[-1]
        if cls is None or last is None or cls == last:
            if last is None and cls is not None:
                classes[-1] = cls
            runs[-1] += char
        else:
            classes.append(cls)
            runs.append(char)
    return list(zip(classes, runs, strict=True))


def directional_paragraphs(
    text: str, default: str = "ltr", threshold: int = 60
) -> list[tuple[str, str]]:
    """Split a mixed-script block into same-direction paragraphs.

    A long LTR island inside an RTL block (an English citation list, say) reads
    badly when the whole block is right-aligned, and Story ignores
    ``unicode-bidi: plaintext``. Short inline islands (a product name, an email)
    stay put; only runs of at least ``threshold`` characters become their own
    paragraph.
    """
    paragraphs: list[tuple[str, str]] = []
    buffer = ""
    buffer_dir: str | None = None
    for cls, run in _script_runs(text):
        if cls is None:
            buffer += run
            continue
        if buffer_dir is None:
            buffer_dir = cls
        elif cls != buffer_dir and len(run) >= threshold:
            paragraphs.append((buffer_dir, buffer))
            buffer = ""
            buffer_dir = cls
        buffer += run
    if buffer.strip():
        paragraphs.append((buffer_dir or default, buffer))
    return paragraphs or [(default, text)]


def sanitize_inline(markup: str | None) -> str:
    """Sanitize inline HTML markup, keeping only harmless formatting tags."""
    if not markup:
        return ""
    if "<" not in markup:
        return html.escape(markup)
    try:
        wrapper = etree.fromstring(f'<div xmlns="{XHTML_NS}">{markup}</div>', parser=_XHTML)
    except etree.XMLSyntaxError:
        return html.escape(markup)
    if wrapper is None:
        return html.escape(markup)
    parts: list[str] = []
    if wrapper.text:
        parts.append(html.escape(wrapper.text))
    for child in wrapper:
        parts.append(_sanitize_node(child))
        if child.tail:
            parts.append(html.escape(child.tail))
    return "".join(parts)


def _sanitize_node(element: etree._Element) -> str:
    tag = _localname(element)
    if tag in ("script", "style"):
        return ""
    inner = html.escape(element.text or "")
    for child in element:
        inner += _sanitize_node(child)
        if child.tail:
            inner += html.escape(child.tail)
    if tag not in _ALLOWED_TAGS:
        return inner
    attributes = "".join(
        f' {name}="{html.escape(value, quote=True)}"'
        for name, value in element.attrib.items()
        if name in _ALLOWED_ATTRS and _safe_attr(name, value)
    )
    if tag in _VOID_TAGS:
        return f"<{tag}{attributes}/>{inner}"
    return f"<{tag}{attributes}>{inner}</{tag}>"


def _safe_attr(name: str, value: str) -> bool:
    if name in ("href", "src"):
        lowered = value.strip().lower()
        return lowered.startswith(_SAFE_URL_PREFIXES)
    return True


def _localname(element: etree._Element) -> str:
    tag = element.tag
    if isinstance(tag, str) and tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag if isinstance(tag, str) else ""


def block_text(block: TextBlock) -> str:
    """Translated text when present, otherwise the source text."""
    return block.translated_text if block.translated_text is not None else (block.source_text or "")


def render_blocks(
    blocks: Sequence[TextBlock],
    *,
    image_src: Mapping[str, str] | None = None,
    direction: str = "ltr",
) -> str:
    """Render a section's blocks to book HTML (consecutive list items group)."""
    image_src = image_src or {}
    parts: list[str] = []
    in_list = False
    for block in blocks:
        if block.type is B.LIST:
            continue
        if block.type is B.LIST_ITEM:
            if not in_list:
                parts.append("<ul>")
                in_list = True
            item_dir = text_direction(strip_markup(block_text(block)), direction)
            parts.append(
                f'<li style="direction:{item_dir}">{sanitize_inline(block_text(block))}</li>'
            )
            continue
        if in_list:
            parts.append("</ul>")
            in_list = False
        parts.append(_render_block(block, image_src, direction))
    if in_list:
        parts.append("</ul>")
    return "\n".join(part for part in parts if part)


def _render_block(block: TextBlock, image_src: Mapping[str, str], direction: str) -> str:
    text = block_text(block)
    block_dir = text_direction(strip_markup(text), direction)
    if block.type is B.HEADING:
        level = min(max(block.level or 1, 1), 6)
        return (
            f'<h{level} class="heading level-{level}" style="direction:{block_dir}">'
            f"{sanitize_inline(text)}</h{level}>"
        )
    if block.type is B.QUOTE:
        return f'<blockquote style="direction:{block_dir}">{sanitize_inline(text)}</blockquote>'
    if block.type is B.CODE:
        return f'<pre class="code">{html.escape(block.plain_text)}</pre>'
    if block.type is B.CAPTION:
        return f'<p class="caption" style="direction:{block_dir}">{sanitize_inline(text)}</p>'
    if block.type is B.TABLE:
        return f'<div class="table" style="direction:{block_dir}">{sanitize_inline(text)}</div>'
    if block.type is B.SEPARATOR:
        return "<hr/>"
    if block.type is B.IMAGE:
        return _render_image(block, image_src)
    if block.type is B.LIST_ITEM:
        return f'<li style="direction:{block_dir}">{sanitize_inline(text)}</li>'
    if "<" in text:  # inline markup present: keep one directional block
        return f'<p style="direction:{block_dir}">{sanitize_inline(text)}</p>'
    paragraphs = directional_paragraphs(text, direction)
    return "\n".join(
        f'<p style="direction:{piece_dir}">{sanitize_inline(piece.strip())}</p>'
        for piece_dir, piece in paragraphs
    )


def _render_image(block: TextBlock, image_src: Mapping[str, str]) -> str:
    src = image_src.get(block.id)
    if not src:
        return ""
    alt = sanitize_attr(block.attributes.get("alt"))
    align = _image_align(block)
    style = _image_size_style(block)
    return (
        f'<div class="image" style="text-align:{align}">'
        f'<img src="{html.escape(src, quote=True)}" alt="{alt}" style="{style}"/></div>'
    )


def _image_align(block: TextBlock) -> str:
    align = block.attributes.get("align")
    return align if align in ("left", "center", "right") else "center"


def _image_size_style(block: TextBlock) -> str:
    pct = block.attributes.get("width_pct")
    style = "height:auto;max-width:100%;"
    if isinstance(pct, (int, float)) and pct > 0:
        style = f"width:{float(pct):g}%;{style}"
    return style


def sanitize_attr(value: object) -> str:
    return html.escape(str(value)) if value else ""


def render_body_html(
    document: CanonicalDocument,
    *,
    font: BookFont,
    language: str,
    direction: str,
    image_src: Mapping[str, str] | None = None,
) -> str:
    """Render the full book body as a single HTML document.

    For PDF sources the first page is the rendered cover, so its text is not
    repeated in the body. Chapter titles and level-1 headings start a new page.
    """
    parts: list[str] = []
    titled = False
    for index, section in enumerate(document.sections):
        if document.source_type == "pdf" and index == 0:
            continue
        anchor = _anchor_id(section)
        if section.title:
            marker = "chapter-title level-1" if titled else "chapter-title level-1 first"
            title_dir = text_direction(sanitize_inline(section.title), direction)
            parts.append(
                f'<h1 class="{marker}" id="{anchor}" style="direction:{title_dir}">'
                f"{sanitize_inline(section.title)}</h1>"
            )
            titled = True
        parts.append(render_blocks(section.blocks, image_src=image_src, direction=direction))
    body = "\n".join(part for part in parts if part)
    if not titled:
        body = body.replace('class="heading level-1"', 'class="heading level-1 first"', 1)
    css = _body_css(font, direction)
    return (
        "<!DOCTYPE html>\n"
        f'<html lang="{html.escape(language, quote=True)}">\n'
        f'<head><meta charset="utf-8"><style>{css}</style></head>\n'
        "<body>\n" + body + "\n</body></html>\n"
    )


def _anchor_id(section: Section) -> str:
    return f"sec-{section.id}"


def _body_css(font: BookFont, direction: str) -> str:
    quote_side = "right" if direction == "rtl" else "left"
    return (
        font_face_css(font)
        + f"body{{margin:0;font-family:{font.family_stack()};font-size:11pt;line-height:1.55;}}"
        + ".chapter-title{font-size:22pt;font-weight:bold;margin:0 0 14pt;}"
        + ".chapter-title, .level-1{page-break-before:always;page-break-after:avoid;}"
        + ".chapter-title.first, .level-1.first{page-break-before:auto;}"
        + "h2,h3,h4,h5,h6{page-break-after:avoid;}"
        + "h1,h2,h3,h4,h5,h6{line-height:1.25;margin:16pt 0 6pt;}"
        + "p{margin:0 0 8pt;}"
        + f"blockquote{{margin:8pt 0;padding:0 14pt;border-{quote_side}:3pt solid #999;"
        + "font-style:italic;}"
        + "pre.code{white-space:pre-wrap;font-family:monospace;font-size:9pt;"
        + "direction:ltr;text-align:left;}"
        + "pre, code, .code{direction:ltr;text-align:left;unicode-bidi:embed;}"
        + ".caption{font-size:9pt;opacity:0.85;}"
        + ".table table{border-collapse:collapse;}"
        + ".table td,.table th{border:0.5pt solid #999;padding:3pt 5pt;}"
        + ".image{text-align:center;margin:10pt 0;}"
        + "img{max-width:100%;height:auto;}"
    )


__all__ = [
    "block_text",
    "directional_paragraphs",
    "render_blocks",
    "render_body_html",
    "sanitize_inline",
    "strip_markup",
    "text_direction",
]
