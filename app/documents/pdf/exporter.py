"""PDF/HTML export.

Rendering is configuration-driven via ``render_backend``:

- ``pymupdf`` (default): a real, print-ready book PDF (cover, table of
  contents, running heads, page numbers, outline) via PyMuPDF's Story engine.
  Pure Python, no system libraries, RTL-aware.
- ``html``: the reflowed HTML source (debug/preview; no pagination).
- ``weasyprint``: PDF via the optional ``pdf`` extra; requires system libraries
  (pango/cairo/gdk-pixbuf). A clear configuration error is raised when missing.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import ClassVar

from app.documents.adapters.base import DocumentType, ExportOptions, ExportResult
from app.documents.book.pdf import render_book_pdf
from app.documents.model import CanonicalDocument
from app.documents.pdf.reflow import render_html
from app.exceptions import ConfigurationError

_HTML_BACKEND = "html"
_PYMUPDF_BACKEND = "pymupdf"
_WEASYPRINT_BACKEND = "weasyprint"


class PdfExporter:
    document_type: ClassVar[DocumentType] = DocumentType.PDF

    def export(self, document: CanonicalDocument, options: ExportOptions) -> ExportResult:
        output_dir = options.output_dir or Path(tempfile.mkdtemp(prefix="book-fork-pdf-"))
        output_dir.mkdir(parents=True, exist_ok=True)

        backend = (options.render_backend or _PYMUPDF_BACKEND).lower()
        if backend == _HTML_BACKEND:
            html_text = render_html(document, options)
            path = output_dir / "translated.html"
            path.write_text(html_text, encoding="utf-8")
            return ExportResult(path=path, media_type="text/html", extension=".html")

        if backend == _PYMUPDF_BACKEND:
            data = render_book_pdf(document, options)
            path = output_dir / "translated.pdf"
            path.write_bytes(data)
            return ExportResult(path=path, media_type="application/pdf", extension=".pdf")

        if backend == _WEASYPRINT_BACKEND:
            return self._render_weasyprint(render_html(document, options), output_dir)

        raise ConfigurationError(f"Unknown PDF render backend {backend!r}.")

    @staticmethod
    def _render_weasyprint(html_text: str, output_dir: Path) -> ExportResult:
        try:
            from weasyprint import HTML
        except Exception as exc:
            raise ConfigurationError(
                "render_backend='weasyprint' requires the 'pdf' extra and system "
                "libraries (pango, cairo, gdk-pixbuf)."
            ) from exc
        path = output_dir / "translated.pdf"
        HTML(string=html_text).write_pdf(str(path))
        return ExportResult(path=path, media_type="application/pdf", extension=".pdf")


__all__ = ["PdfExporter"]
