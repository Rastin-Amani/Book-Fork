"""EPUB export.

Rebuilds a valid EPUB 3 from the canonical model: package metadata, manifest,
spine, navigation (both the EPUB 3 ``nav`` and the legacy ``toc.ncx``), a
generated cover, embedded book fonts and book CSS. Language and text-direction
attributes come from the target language configuration, so RTL targets are
correct and reading progression is right-to-left.

Only translatable text is replaced; images, links and document order are
preserved.
"""

from __future__ import annotations

import html
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, ClassVar

from lxml import etree

from app.documents.adapters.base import (
    DocumentType,
    ExportOptions,
    ExportResult,
)
from app.documents.book.cover import CoverSpec, render_cover_png
from app.documents.book.fonts import BookFont, book_font
from app.documents.book.html import directional_paragraphs, strip_markup, text_direction
from app.documents.ids import section_id
from app.documents.model import BlockType as B
from app.documents.model import CanonicalDocument, Section, TextBlock
from app.exceptions import ConfigurationError

XHTML_NS = "http://www.w3.org/1999/xhtml"
EPUB_NS = "http://www.idpf.org/2007/ops"
_NAV_TITLES = {
    "fa": "فهرست",
    "ar": "المحتويات",
    "ur": "فہرست",
    "he": "תוכן העניינים",
    "ps": "منځپانګه",
}
_CONTAINER_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<container version="1.0" '
    'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
    "  <rootfiles>\n"
    '    <rootfile full-path="OEBPS/content.opf" '
    'media-type="application/oebps-package+xml"/>\n'
    "  </rootfiles>\n"
    "</container>\n"
)
_BOOK_CSS_HREF = "styles/book.css"
_COVER_PAGE = "cover.xhtml"
_IMAGE_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/gif": "gif",
    "image/svg+xml": "svg",
    "image/webp": "webp",
}


def _xhtml_parser() -> etree.XMLParser:
    return etree.XMLParser(
        recover=True, resolve_entities=False, load_dtd=False, no_network=True, huge_tree=False
    )


def _localname(element: etree._Element) -> str:
    tag = element.tag
    if isinstance(tag, str) and tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag if isinstance(tag, str) else ""


def _append_inner(parent: etree._Element, inner: str | None) -> None:
    """Append a possibly-marked-up fragment, preserving inline formatting."""
    if not inner:
        return
    wrapper = etree.fromstring(f'<div xmlns="{XHTML_NS}">{inner}</div>', parser=_xhtml_parser())
    if wrapper is None:
        parent.text = (parent.text or "") + inner
        return
    parent.text = (parent.text or "") + (wrapper.text or "")
    for child in wrapper:
        if _localname(child) in ("script", "style"):
            continue
        parent.append(child)


class EpubExporter:
    document_type: ClassVar[DocumentType] = DocumentType.EPUB

    def export(self, document: CanonicalDocument, options: ExportOptions) -> ExportResult:
        output_dir = options.output_dir or Path(tempfile.mkdtemp(prefix="book-fork-epub-"))
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "translated.epub"

        language = options.target_language or document.metadata.language or "und"
        direction = options.target_direction
        font = book_font(language, script=options.target_script, font_dir=options.font_dir)
        title = options.document_title or document.metadata.title or "Translated document"
        asset_hrefs = self._asset_hrefs(document)

        content_files: list[tuple[str, Section]] = []
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as epub:
            # mimetype MUST be first and uncompressed.
            epub.writestr(
                zipfile.ZipInfo("mimetype"),
                "application/epub+zip",
                compress_type=zipfile.ZIP_STORED,
            )
            epub.writestr("META-INF/container.xml", _CONTAINER_XML)

            asset_styles = [
                href
                for asset in document.assets
                if asset.media_type == "text/css"
                if (href := asset_hrefs.get(asset.id))
            ]
            stylesheets = [_BOOK_CSS_HREF, *asset_styles]
            for section in self._output_sections(document):
                name = f"OEBPS/{section.id}.xhtml"
                content_files.append((name, section))
                epub.writestr(
                    name,
                    self._render_section(document, section, language, direction, stylesheets),
                )

            epub.writestr("OEBPS/nav.xhtml", self._render_nav(content_files, language, direction))
            epub.writestr("OEBPS/toc.ncx", self._render_ncx(document, content_files, language))
            epub.writestr(
                "OEBPS/styles/book.css",
                _book_css(font, direction).encode("utf-8"),
            )
            cover_data, cover_name, cover_mime = self._cover_image(
                document, options, font, title, direction
            )
            epub.writestr(
                f"OEBPS/{_COVER_PAGE}",
                self._render_cover_page(title, language, direction, cover_name),
            )
            epub.writestr(f"OEBPS/{cover_name}", cover_data)

            for _weight, _style, path in _font_files(font):
                epub.writestr(f"OEBPS/fonts/{path.name}", path.read_bytes())

            for asset in document.assets:
                if asset.attributes.get("role") == "cover":
                    continue
                href = asset_hrefs.get(asset.id)
                if href is None:
                    continue
                data = self._asset_data(asset, options)
                if data is None:
                    continue
                epub.writestr(f"OEBPS/{href}", data)

            epub.writestr(
                "OEBPS/content.opf",
                self._render_opf(
                    document,
                    content_files,
                    asset_hrefs,
                    language,
                    direction,
                    font,
                    cover_name,
                    cover_mime,
                ),
            )

        return ExportResult(
            path=output_path,
            media_type="application/epub+zip",
            extension=".epub",
        )

    # -- assets --------------------------------------------------------------
    @staticmethod
    def _asset_hrefs(document: CanonicalDocument) -> dict[str, str]:
        hrefs: dict[str, str] = {}
        for asset in document.assets:
            safe_name = PurePosixPath(asset.filename).name or asset.id
            hrefs[asset.id] = f"assets/{asset.id}/{safe_name}"
        return hrefs

    @staticmethod
    def _asset_data(asset: Any, options: ExportOptions) -> bytes | None:
        if options.asset_resolver is None:
            return None
        try:
            return options.asset_resolver(asset)
        except Exception as exc:
            raise ConfigurationError(
                f"Could not resolve asset {asset.id!r} for EPUB export."
            ) from exc

    def _cover_image(
        self,
        document: CanonicalDocument,
        options: ExportOptions,
        font: BookFont,
        title: str,
        direction: str,
    ) -> tuple[bytes, str, str]:
        """Use the document's own cover when present, else generate one."""
        resolver = options.asset_resolver
        if resolver is not None:
            for asset in document.assets:
                if asset.attributes.get("role") != "cover" or not asset.media_type.startswith(
                    "image/"
                ):
                    continue
                try:
                    data = resolver(asset)
                except Exception:
                    data = None
                if data:
                    extension = _IMAGE_EXTENSIONS.get(asset.media_type, "png")
                    return data, f"cover.{extension}", asset.media_type
        generated = render_cover_png(
            CoverSpec(
                title=title,
                authors=tuple(document.metadata.authors),
                publisher=document.metadata.publisher,
                direction=direction,
            ),
            font,
        )
        return generated, "cover.png", "image/png"

    # -- rendering -----------------------------------------------------------
    def _output_sections(self, document: CanonicalDocument) -> list[Section]:
        """Group a PDF source into chapters at its recovered level-1 headings.

        EPUB sources already carry titled sections, so they are returned as-is.
        """
        has_chapters = any(
            block.type is B.HEADING and (block.level or 1) == 1 for block in document.iter_blocks()
        )
        if document.source_type != "pdf" or not has_chapters:
            return document.sections

        chapters: list[Section] = []
        current: Section | None = None
        for index, section in enumerate(document.sections):
            if index == 0:  # page 1 is the rendered cover
                continue
            for block in section.blocks:
                if block.type is B.HEADING and (block.level or 1) == 1:
                    current = Section(
                        id=section_id(len(chapters)),
                        source_order=len(chapters),
                        title=block.plain_text or None,
                        blocks=[],
                    )
                    chapters.append(current)
                    continue
                if current is None:
                    current = Section(
                        id=section_id(len(chapters)),
                        source_order=len(chapters),
                        title=None,
                        blocks=[],
                    )
                    chapters.append(current)
                current.blocks.append(block)
        return chapters or document.sections

    def _render_section(
        self,
        document: CanonicalDocument,
        section: Section,
        language: str,
        direction: str,
        stylesheets: list[str],
    ) -> bytes:
        root = etree.Element(
            f"{{{XHTML_NS}}}html",
            nsmap={None: XHTML_NS},
            attrib={
                "{http://www.w3.org/XML/1998/namespace}lang": language,
                "lang": language,
                "dir": direction,
            },
        )
        head = etree.SubElement(root, f"{{{XHTML_NS}}}head")
        title = etree.SubElement(head, f"{{{XHTML_NS}}}title")
        title.text = section.title or document.metadata.title or section.id
        etree.SubElement(head, f"{{{XHTML_NS}}}meta", attrib={"charset": "utf-8"})
        for href in stylesheets:
            etree.SubElement(
                head,
                f"{{{XHTML_NS}}}link",
                attrib={"rel": "stylesheet", "type": "text/css", "href": str(PurePosixPath(href))},
            )
        body = etree.SubElement(root, f"{{{XHTML_NS}}}body")
        if section.title:
            heading = etree.SubElement(body, f"{{{XHTML_NS}}}h1", attrib={"class": "chapter-title"})
            heading.set("dir", text_direction(section.title, direction))
            heading.text = section.title

        list_stack: list[tuple[str, etree._Element]] = []
        synthetic_list: etree._Element | None = None
        synthetic_ordered: bool | None = None
        for block in section.blocks:
            text = self._block_text(block) or ""
            # Items from a PDF source have no <ul>/<ol> container; group runs of
            # them so the output is valid XHTML and gets real bullets/numbers.
            if block.type is B.LIST_ITEM and not list_stack:
                ordered = block.attributes.get("list_style") == "ordered"
                if synthetic_list is None or synthetic_ordered is not ordered:
                    synthetic_list = etree.SubElement(
                        body, f"{{{XHTML_NS}}}{'ol' if ordered else 'ul'}"
                    )
                    synthetic_ordered = ordered
                item = etree.SubElement(synthetic_list, f"{{{XHTML_NS}}}li")
                item.set("dir", text_direction(strip_markup(text), direction))
                _append_inner(item, self._block_text(block))
                continue
            synthetic_list = None
            if block.type is B.PARAGRAPH and text and "<" not in text:
                pieces = directional_paragraphs(text, direction)
                if len(pieces) > 1:
                    for piece_dir, piece in pieces:
                        paragraph = etree.SubElement(
                            body, f"{{{XHTML_NS}}}p", attrib={"dir": piece_dir}
                        )
                        paragraph.text = piece.strip()
                    continue
            element = self._render_block(document, block, list_stack, direction)
            if element is not None:
                body.append(element)

        return etree.tostring(
            root, xml_declaration=True, encoding="utf-8", doctype="<!DOCTYPE html>", method="xml"
        )

    def _render_block(
        self,
        document: CanonicalDocument,
        block: TextBlock,
        list_stack: list[tuple[str, etree._Element]],
        direction: str,
    ) -> etree._Element | None:
        block_dir = text_direction(strip_markup(self._block_text(block)), direction)
        if block.type is B.LIST:
            node = etree.Element(f"{{{XHTML_NS}}}ul")
            _append_inner(node, None)
            list_stack.append((block.id, node))
            return node
        if block.type is B.LIST_ITEM:
            parent = (
                list_stack[-1][1] if list_stack and list_stack[-1][0] == block.parent_id else None
            )
            node = etree.Element(f"{{{XHTML_NS}}}li", attrib={"dir": block_dir})
            _append_inner(node, self._block_text(block))
            if parent is not None:
                parent.append(node)
                return None
            return node
        # any non-list block closes open lists
        list_stack.clear()

        text = self._block_text(block)
        if block.type is B.HEADING:
            node = etree.Element(f"{{{XHTML_NS}}}h{block.level or 1}", attrib={"dir": block_dir})
            _append_inner(node, text)
            return node
        if block.type is B.QUOTE:
            node = etree.Element(f"{{{XHTML_NS}}}blockquote", attrib={"dir": block_dir})
            _append_inner(node, text)
            return node
        if block.type is B.CAPTION:
            node = etree.Element(f"{{{XHTML_NS}}}p", attrib={"class": "caption", "dir": block_dir})
            _append_inner(node, text)
            return node
        if block.type is B.CODE:
            node = etree.Element(f"{{{XHTML_NS}}}pre", attrib={"dir": "ltr"})
            node.text = self._plain(block)
            return node
        if block.type is B.TABLE:
            node = etree.Element(f"{{{XHTML_NS}}}table", attrib={"dir": block_dir})
            _append_inner(node, text)
            return node
        if block.type is B.SEPARATOR:
            return etree.Element(f"{{{XHTML_NS}}}hr")
        if block.type is B.IMAGE:
            return self._render_image(document, block)
        node = etree.Element(f"{{{XHTML_NS}}}p", attrib={"dir": block_dir})
        _append_inner(node, text)
        return node

    def _render_image(self, document: CanonicalDocument, block: TextBlock) -> etree._Element | None:
        src = block.attributes.get("src") or ""
        asset = self._match_asset(document, src)
        if asset is None:
            return None
        align = block.attributes.get("align")
        container = etree.Element(
            f"{{{XHTML_NS}}}div",
            attrib={
                "class": "image",
                "style": f"text-align:{align if align in ('left', 'right') else 'center'}",
            },
        )
        node = etree.SubElement(container, f"{{{XHTML_NS}}}img")
        node.set("src", f"assets/{asset.id}/{PurePosixPath(asset.filename).name}")
        if block.attributes.get("alt"):
            node.set("alt", str(block.attributes["alt"]))
        node.set("style", _image_style(block))
        return container

    @staticmethod
    def _match_asset(document: CanonicalDocument, src: str) -> Any:
        if not src:
            return None
        basename = PurePosixPath(src).name
        for asset in document.assets:
            if PurePosixPath(asset.filename).name == basename and asset.media_type.startswith(
                "image/"
            ):
                return asset
        return None

    @staticmethod
    def _block_text(block: TextBlock) -> str | None:
        return block.translated_text if block.translated_text is not None else block.source_text

    @staticmethod
    def _plain(block: TextBlock) -> str:
        text = block.translated_text if block.translated_text is not None else block.plain_text
        return text

    def _render_cover_page(
        self, title: str, language: str, direction: str, cover_href: str
    ) -> bytes:
        root = etree.Element(
            f"{{{XHTML_NS}}}html",
            nsmap={None: XHTML_NS},
            attrib={
                "{http://www.w3.org/XML/1998/namespace}lang": language,
                "lang": language,
                "dir": direction,
            },
        )
        head = etree.SubElement(root, f"{{{XHTML_NS}}}head")
        etree.SubElement(head, f"{{{XHTML_NS}}}title").text = title
        etree.SubElement(head, f"{{{XHTML_NS}}}meta", attrib={"charset": "utf-8"})
        etree.SubElement(
            head,
            f"{{{XHTML_NS}}}link",
            attrib={"rel": "stylesheet", "type": "text/css", "href": _BOOK_CSS_HREF},
        )
        body = etree.SubElement(root, f"{{{XHTML_NS}}}body", attrib={"class": "cover-page"})
        section = etree.SubElement(body, f"{{{XHTML_NS}}}div", attrib={"class": "cover"})
        image = etree.SubElement(
            section, f"{{{XHTML_NS}}}img", attrib={"src": cover_href, "alt": title}
        )
        image.set("{http://www.w3.org/XML/1998/namespace}lang", language)
        return etree.tostring(
            root, xml_declaration=True, encoding="utf-8", doctype="<!DOCTYPE html>", method="xml"
        )

    def _render_nav(
        self, content_files: list[tuple[str, Section]], language: str, direction: str
    ) -> bytes:
        root = etree.Element(
            f"{{{XHTML_NS}}}html",
            nsmap={None: XHTML_NS},
            attrib={
                "{http://www.w3.org/XML/1998/namespace}lang": language,
                "lang": language,
                "dir": direction,
            },
        )
        head = etree.SubElement(root, f"{{{XHTML_NS}}}head")
        etree.SubElement(head, f"{{{XHTML_NS}}}title").text = "Contents"
        etree.SubElement(head, f"{{{XHTML_NS}}}meta", attrib={"charset": "utf-8"})
        etree.SubElement(
            head,
            f"{{{XHTML_NS}}}link",
            attrib={"rel": "stylesheet", "type": "text/css", "href": _BOOK_CSS_HREF},
        )
        body = etree.SubElement(root, f"{{{XHTML_NS}}}body")
        nav = etree.SubElement(
            body, f"{{{XHTML_NS}}}nav", attrib={f"{{{EPUB_NS}}}type": "toc", "id": "toc"}
        )
        etree.SubElement(nav, f"{{{XHTML_NS}}}h1").text = _NAV_TITLES.get(
            language.split("-", 1)[0].lower(), "Contents"
        )
        ordered = etree.SubElement(nav, f"{{{XHTML_NS}}}ol")
        for name, section in content_files:
            item = etree.SubElement(ordered, f"{{{XHTML_NS}}}li")
            anchor = etree.SubElement(
                item, f"{{{XHTML_NS}}}a", attrib={"href": name.split("/")[-1]}
            )
            anchor.text = section.title or section.id

        landmarks = etree.SubElement(
            body,
            f"{{{XHTML_NS}}}nav",
            attrib={f"{{{EPUB_NS}}}type": "landmarks", "id": "landmarks"},
        )
        etree.SubElement(landmarks, f"{{{XHTML_NS}}}h2").text = "Landmarks"
        land_ol = etree.SubElement(landmarks, f"{{{XHTML_NS}}}ol")
        self._landmark(land_ol, "cover", _COVER_PAGE, "Cover")
        self._landmark(land_ol, "toc", "nav.xhtml", "Table of Contents")
        if content_files:
            self._landmark(
                land_ol, "bodymatter", content_files[0][0].split("/")[-1], "Start of Content"
            )
        return etree.tostring(
            root, xml_declaration=True, encoding="utf-8", doctype="<!DOCTYPE html>", method="xml"
        )

    @staticmethod
    def _landmark(ordered: etree._Element, kind: str, href: str, label: str) -> None:
        item = etree.SubElement(ordered, f"{{{XHTML_NS}}}li")
        anchor = etree.SubElement(
            item, f"{{{XHTML_NS}}}a", attrib={f"{{{EPUB_NS}}}type": kind, "href": href}
        )
        anchor.text = label

    def _render_ncx(
        self, document: CanonicalDocument, content_files: list[tuple[str, Section]], language: str
    ) -> str:
        points: list[str] = []
        for order, (name, section) in enumerate(content_files, start=1):
            label = html.escape(section.title or section.id)
            points.append(
                f'<navPoint id="navPoint-{order}" playOrder="{order}">'
                f"<navLabel><text>{label}</text></navLabel>"
                f'<content src="{html.escape(name.split("/")[-1], quote=True)}"/>'
                "</navPoint>"
            )
        identifier = document.metadata.identifier or (document.document_id or "book-fork-document")
        uid = html.escape(identifier, quote=True)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
            f'  <head><meta name="dtb:uid" content="{uid}"/></head>\n'
            f"  <docTitle><text>{html.escape(document.metadata.title or 'Translated document')}"
            "</text></docTitle>\n"
            f"  <navMap>{''.join(points)}</navMap>\n"
            "</ncx>\n"
        )

    def _render_opf(
        self,
        document: CanonicalDocument,
        content_files: list[tuple[str, Section]],
        asset_hrefs: dict[str, str],
        language: str,
        direction: str,
        font: BookFont,
        cover_name: str,
        cover_mime: str,
    ) -> str:
        modified = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        identifier = document.metadata.identifier or (document.document_id or "book-fork-document")
        manifest: list[str] = [
            f'<item id="{section.id}" href="{section.id}.xhtml" '
            'media-type="application/xhtml+xml"/>'
            for _name, section in content_files
        ]
        manifest.append(
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        )
        manifest.append('<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>')
        manifest.append(
            f'<item id="cover-page" href="{_COVER_PAGE}" media-type="application/xhtml+xml"/>'
        )
        manifest.append(
            f'<item id="cover-image" href="{cover_name}" '
            f'media-type="{cover_mime}" properties="cover-image"/>'
        )
        manifest.append(f'<item id="book-css" href="{_BOOK_CSS_HREF}" media-type="text/css"/>')
        for weight, style, path in _font_files(font):
            manifest.append(
                f'<item id="font-{path.stem}-{weight}-{style}" href="fonts/{path.name}" '
                'media-type="font/ttf"/>'
            )
        for asset in document.assets:
            if asset.attributes.get("role") == "cover":
                continue
            href = asset_hrefs.get(asset.id)
            if href is None:
                continue
            manifest.append(
                f'<item id="{asset.id}" href="{html.escape(href, quote=True)}" '
                f'media-type="{html.escape(asset.media_type, quote=True)}"/>'
            )
        spine_items = [
            '<itemref idref="cover-page"/>',
            *[f'<itemref idref="{section.id}"/>' for _name, section in content_files],
        ]
        spine = "".join(spine_items)
        progression = ' page-progression-direction="rtl"' if direction == "rtl" else ""
        creators = "".join(
            f"<dc:creator>{html.escape(author)}</dc:creator>"
            for author in document.metadata.authors
        )
        publisher = (
            f"<dc:publisher>{html.escape(document.metadata.publisher)}</dc:publisher>"
            if document.metadata.publisher
            else ""
        )
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
            'unique-identifier="bookid" '
            f'xml:lang="{html.escape(language, quote=True)}">\n'
            '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
            f'    <dc:identifier id="bookid">{html.escape(identifier)}</dc:identifier>\n'
            f"    <dc:title>{html.escape(document.metadata.title or 'Translated document')}"
            "</dc:title>\n"
            f"    {creators}\n"
            f"    {publisher}\n"
            f"    <dc:language>{html.escape(language)}</dc:language>\n"
            f'    <meta name="cover" content="cover-image"/>\n'
            f'    <meta property="dcterms:modified">{modified}</meta>\n'
            "  </metadata>\n"
            f"  <manifest>{''.join(manifest)}</manifest>\n"
            f'  <spine toc="ncx"{progression}>{spine}</spine>\n'
            "  <guide>\n"
            f'    <reference type="cover" title="Cover" href="{_COVER_PAGE}"/>\n'
            '    <reference type="toc" title="Contents" href="nav.xhtml"/>\n'
            "  </guide>\n"
            "</package>\n"
        )


def _image_style(block: TextBlock) -> str:
    pct = block.attributes.get("width_pct")
    style = "height:auto;max-width:100%;"
    if isinstance(pct, (int, float)) and pct > 0:
        style = f"width:{float(pct):g}%;{style}"
    return style


def _font_files(font: BookFont) -> list[tuple[str, str, Path]]:
    files: list[tuple[str, str, Path]] = [
        ("normal", "normal", font.regular),
        ("bold", "normal", font.bold),
    ]
    if font.italic:
        files.append(("normal", "italic", font.italic))
    if font.bold_italic:
        files.append(("bold", "italic", font.bold_italic))
    return files


def _book_css(font: BookFont, direction: str) -> str:
    align = "right" if direction == "rtl" else "left"
    quote_side = "right" if direction == "rtl" else "left"
    faces = "".join(
        f"@font-face{{font-family:'{font.family}';font-weight:{weight};"
        f"font-style:{style};src:url('../fonts/{path.name}');}}"
        for weight, style, path in _font_files(font)
    )
    return (
        faces
        + f"html,body{{font-family:{font.family_stack()};direction:{direction};"
        + f"text-align:{align};line-height:1.55;}}"
        + ".chapter-title{font-size:1.6em;margin:0 0 .8em;}"
        + "p{margin:0 0 .8em;}"
        + f"blockquote{{margin:.8em 0;padding:0 1em;border-{quote_side}:3px solid #999;"
        + "font-style:italic;}"
        + "pre{white-space:pre-wrap;direction:ltr;text-align:left;}"
        + ".caption{font-size:.9em;opacity:.85;}"
        + ".image{margin:.8em 0;}"
        + "img{max-width:100%;height:auto;}"
        + ".cover-page{text-align:center;}"
        + ".cover img{max-width:100%;max-height:98vh;}"
        + ".center{text-align:center;}"
    )


__all__ = ["EpubExporter"]
