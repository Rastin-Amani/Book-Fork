"""Reflowed HTML rendering of the canonical model (input to PDF/HTML export).

Pure and deterministic so it can be tested without any PDF system libraries.
Language and text direction come from configuration, so RTL and mixed-direction
text are laid out correctly.
"""

from __future__ import annotations

import html
from pathlib import Path

from app.documents.adapters.base import ExportOptions
from app.documents.model import BlockType as B
from app.documents.model import CanonicalDocument, TextBlock

_FONT_EXTENSIONS = (".ttf", ".otf", ".woff", ".woff2")


def _font_faces(font_dir: str | None) -> tuple[str, str]:
    """Return (@font-face CSS, font-family) from configured fonts."""
    if not font_dir:
        return "", "serif"
    directory = Path(font_dir)
    if not directory.is_dir():
        return "", "serif"
    faces: list[str] = []
    for path in sorted(directory.iterdir()):
        if path.suffix.lower() in _FONT_EXTENSIONS:
            faces.append(
                "@font-face{font-family:'BookForkBody';"
                f"src:url('{html.escape(path.as_uri())}');"
                "font-display:swap;}"
            )
    return "".join(faces), "BookForkBody, serif" if faces else "serif"


def _block_html(block: TextBlock) -> str:
    text = block.translated_text if block.translated_text is not None else block.source_text
    if block.type is B.HEADING:
        level = min(max(block.level or 1, 1), 6)
        return f"<h{level}>{text or ''}</h{level}>"
    if block.type is B.QUOTE:
        return f"<blockquote>{text or ''}</blockquote>"
    if block.type is B.CODE:
        return f"<pre>{html.escape(block.plain_text)}</pre>"
    if block.type is B.CAPTION:
        return f'<p class="caption">{text or ""}</p>'
    if block.type is B.LIST or block.type is B.LIST_ITEM:
        return f'<p class="list-item">{text or ""}</p>'
    if block.type is B.TABLE:
        return f'<div class="table">{text or ""}</div>'
    if block.type is B.SEPARATOR:
        return "<hr/>"
    if block.type is B.IMAGE:
        return ""  # images are not embedded in the HTML reflow
    return f"<p>{text or ''}</p>"


def render_html(
    document: CanonicalDocument, options: ExportOptions, *, title: str | None = None
) -> str:
    language = options.target_language or document.metadata.language or "und"
    direction = options.target_direction
    faces, family = _font_faces(options.font_dir)
    page_title = title or options.document_title or document.metadata.title or "Translated document"

    sections_html: list[str] = []
    for section in document.sections:
        if section.title:
            sections_html.append(f'<h1 class="section-title">{html.escape(section.title)}</h1>')
        for block in section.blocks:
            sections_html.append(_block_html(block))

    body_css = (
        f"body{{font-family:{family};line-height:1.6;margin:2rem auto;"
        "max-width:46rem;padding:0 1rem;}\n"
    )
    return (
        "<!doctype html>\n"
        f'<html lang="{html.escape(language, quote=True)}" '
        f'dir="{html.escape(direction, quote=True)}">\n'
        '<head>\n<meta charset="utf-8">\n'
        f"<title>{html.escape(page_title)}</title>\n"
        "<style>\n"
        f"{faces}\n"
        f"{body_css}"
        "h1,h2,h3,h4,h5,h6{line-height:1.25;}\n"
        "blockquote{border-inline-start:3px solid #999;margin:1rem 0;"
        "padding-inline-start:1rem;}\n"
        "pre{white-space:pre-wrap;}\n"
        ".caption,.list-item{opacity:.9;}\n"
        "</style>\n</head>\n<body>\n" + "\n".join(sections_html) + "\n</body>\n</html>\n"
    )
