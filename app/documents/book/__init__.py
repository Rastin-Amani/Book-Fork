"""Book rendering: covers, fonts and print/EPUB-oriented output.

Everything here works from the canonical model. PDF output uses PyMuPDF's
``Story`` engine (pure Python, RTL-aware); EPUB output is a standards-compliant
EPUB 3 rebuild.
"""

from app.documents.book.fonts import BookFont, book_font, script_for_language

__all__ = ["BookFont", "book_font", "script_for_language"]
