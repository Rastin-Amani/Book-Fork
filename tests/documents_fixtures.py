"""Generated document fixtures for tests (no committed binary blobs)."""

from __future__ import annotations

import base64
import zipfile
from pathlib import Path

import pymupdf

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M8AAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
)

_CONTAINER = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
    '<rootfiles><rootfile full-path="OEBPS/content.opf" '
    'media-type="application/oebps-package+xml"/></rootfiles></container>'
)

_CHAPTER = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en">
<head><title>{title}</title><link rel="stylesheet" type="text/css" href="style.css"/></head>
<body>
<h1 id="ch-{index}">{title}</h1>
<p>Hello <em>world</em>, this is paragraph one of {title}.</p>
<p>Visit <a href="https://example.com/page">our site</a> for more, or email a@b.co.</p>
<ul><li>First item</li><li>Second item</li></ul>
<blockquote><p>A quoted line.</p></blockquote>
</body>
</html>
"""

_NAV = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>Contents</title></head>
<body><nav epub:type="toc" id="toc"><ol></ol></nav></body>
</html>
"""


def _opf(
    chapter_count: int, with_image: bool, *, language: str = "en", with_cover: bool = False
) -> str:
    items = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="css" href="style.css" media-type="text/css"/>',
    ]
    for index in range(chapter_count):
        items.append(
            f'<item id="ch{index}" href="chapter{index}.xhtml" media-type="application/xhtml+xml"/>'
        )
    if with_image:
        items.append('<item id="img0" href="images/pic.png" media-type="image/png"/>')
    cover_meta = ""
    if with_cover:
        items.append(
            '<item id="coverimg" href="images/cover.png" '
            'media-type="image/png" properties="cover-image"/>'
        )
        cover_meta = '<meta name="cover" content="coverimg"/>'
    spine = "".join(f'<itemref idref="ch{i}"/>' for i in range(chapter_count))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<dc:identifier id="bookid">book-fork-test-1</dc:identifier>'
        "<dc:title>Test Book</dc:title>"
        "<dc:creator>Ada Lovelace</dc:creator>"
        f"<dc:language>{language}</dc:language>"
        f"{cover_meta}"
        "</metadata>"
        f"<manifest>{''.join(items)}</manifest>"
        f"<spine>{spine}</spine>"
        "</package>"
    )


def write_epub(
    path: Path,
    *,
    chapters: int = 2,
    with_image: bool = False,
    with_cover: bool = False,
    bad_mimetype: bool = False,
    missing_mimetype: bool = False,
) -> Path:
    """Create a valid (or deliberately invalid) EPUB at ``path``."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as epub:
        if not missing_mimetype:
            mimetype = "not-an-epub" if bad_mimetype else "application/epub+zip"
            epub.writestr(zipfile.ZipInfo("mimetype"), mimetype, compress_type=zipfile.ZIP_STORED)
        epub.writestr("META-INF/container.xml", _CONTAINER)
        epub.writestr("OEBPS/content.opf", _opf(chapters, with_image, with_cover=with_cover))
        epub.writestr("OEBPS/nav.xhtml", _NAV)
        epub.writestr("OEBPS/style.css", "body{font-family:serif;}")
        for index in range(chapters):
            epub.writestr(
                f"OEBPS/chapter{index}.xhtml",
                _CHAPTER.format(title=f"Chapter {index + 1}", index=index),
            )
        if with_image:
            epub.writestr("OEBPS/images/pic.png", PNG_1X1)
        if with_cover:
            epub.writestr("OEBPS/images/cover.png", PNG_1X1)
    return path


def write_malformed_epub(path: Path) -> Path:
    """A file named .epub that is not a zip archive."""
    path.write_bytes(b"this is definitely not a zip file")
    return path


def write_traversal_zip(path: Path) -> Path:
    """An EPUB-shaped zip containing a path-traversal entry."""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip")
        archive.writestr("../escape.txt", "evil")
    return path


def write_zip_bomb(path: Path, *, ratio_entries: int = 200) -> Path:
    """A zip whose uncompressed size vastly exceeds its compressed size."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("bomb.bin", b"\x00" * (10_000_000))
    return path


def write_pdf(path: Path, *, pages: int = 2, heading: bool = True) -> Path:
    """Create a multi-page text PDF."""
    document = pymupdf.open()
    for index in range(pages):
        page = document.new_page()
        if heading:
            page.insert_text((72, 72), f"Page {index + 1} Heading", fontsize=24)
            y = 110
        else:
            y = 72
        page.insert_text((72, y), f"Body text on page {index + 1}. More words follow here.")
    document.save(str(path))
    document.close()
    return path


def write_image_pdf(
    path: Path, *, image_rect: tuple[float, float, float, float] = (72, 120, 272, 320)
) -> Path:
    """Create a two-page PDF whose second page interleaves text and an image."""
    document = pymupdf.open()
    cover = document.new_page(width=595, height=842)
    cover.insert_text((72, 72), "Cover", fontsize=24)
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 72), "Before image paragraph.", fontsize=12)
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 64, 64), 0)
    pixmap.set_rect(pixmap.irect, (200, 30, 30))
    page.insert_image(pymupdf.Rect(*image_rect), stream=pixmap.tobytes("png"))
    page.insert_text((72, 360), "After image paragraph.", fontsize=12)
    document.save(str(path))
    document.close()
    return path


def write_text_epub(
    path: Path,
    *,
    language: str = "en",
    title: str = "Text",
    paragraphs: tuple[str, ...] = (),
) -> Path:
    """Create a minimal EPUB whose body contains the given paragraphs.

    Used for multilingual fixtures (German, Arabic, Persian, Japanese, mixed
    direction) without committing binary blobs.
    """
    body = "\n".join(f"<p>{text}</p>" for text in paragraphs)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as epub:
        epub.writestr(
            zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED
        )
        epub.writestr("META-INF/container.xml", _CONTAINER)
        epub.writestr("OEBPS/content.opf", _opf(1, False, language=language))
        epub.writestr("OEBPS/nav.xhtml", _NAV)
        epub.writestr("OEBPS/style.css", "body{font-family:serif;}")
        epub.writestr(
            "OEBPS/chapter0.xhtml",
            (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<html xmlns="http://www.w3.org/1999/xhtml"'
                f' xml:lang="{language}" lang="{language}">'
                f"<head><title>{title}</title></head><body>"
                f'<h1 id="ch-0">{title}</h1>{body}</body></html>'
            ),
        )
    return path


def write_unicode_pdf(path: Path, *, text: str = "日本語のテキスト") -> Path:
    """Create a PDF containing CJK Unicode text using a builtin CJK font."""
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Unicode sample", fontsize=18)
    page.insert_text((72, 110), text, fontname="japan", fontsize=14)
    document.save(str(path))
    document.close()
    return path


def write_table_pdf(path: Path) -> Path:
    """Create a PDF with a simple heading and a tabular layout of text."""
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Report", fontsize=20)
    rows = [("Region", "Units"), ("North", "120"), ("South", "98")]
    for index, (left, right) in enumerate(rows):
        y = 110 + index * 24
        page.insert_text((72, y), left)
        page.insert_text((220, y), right)
    document.save(str(path))
    document.close()
    return path
