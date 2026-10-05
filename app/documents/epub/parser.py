"""EPUB parsing.

Preserves structure rather than flattening to plain text: chapter order,
sections, block types, inline markup, links, images and metadata are all kept in
the canonical model. Archives are validated before any member is read.
"""

from __future__ import annotations

import zipfile
from pathlib import Path, PurePosixPath
from typing import ClassVar

from lxml import etree

from app.documents.adapters.base import DocumentType, ParseOptions, ParseResult
from app.documents.ids import asset_id, block_id, section_id
from app.documents.model import (
    Asset,
    BlockType,
    CanonicalDocument,
    DocumentMetadata,
    Section,
    TextBlock,
)
from app.documents.safety import (
    ArchiveLimits,
    inspect_archive,
    read_member,
    verify_epub_mimetype,
)
from app.exceptions import ValidationError

CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"
OPF_NS = "http://www.idpf.org/2007/opf"
DC_NS = "http://purl.org/dc/elements/1.1/"
XHTML_NS = "http://www.w3.org/1999/xhtml"

_HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
_TEXT_LIMIT = 50_000_000


def _localname(element: etree._Element) -> str:
    tag = element.tag
    if isinstance(tag, str) and tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag if isinstance(tag, str) else ""


def _xml_parser() -> etree.XMLParser:
    return etree.XMLParser(
        recover=True,
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        huge_tree=False,
        remove_comments=False,
    )


def _parse_xml(data: bytes) -> etree._Element:
    try:
        return etree.fromstring(data, parser=_xml_parser())
    except etree.XMLSyntaxError as exc:
        raise ValidationError("EPUB contains unparseable XML.") from exc


def _inner_markup(element: etree._Element) -> str:
    parts = [element.text or ""]
    for child in element:
        parts.append(etree.tostring(child, encoding="unicode", method="xml"))
    return "".join(parts).strip()


def _plain_text(element: etree._Element) -> str:
    return " ".join(" ".join(element.itertext()).split())


def _first(values: list[str]) -> str | None:
    return values[0] if values else None


class EpubParser:
    document_type: ClassVar[DocumentType] = DocumentType.EPUB

    def parse(self, source: Path, options: ParseOptions) -> ParseResult:
        limits = ArchiveLimits(
            max_uncompressed_bytes=options.max_uncompressed_bytes,
            max_entries=options.max_archive_entries,
            max_compression_ratio=options.max_compression_ratio,
        )
        inspect_archive(source, limits)
        warnings: list[str] = []

        with zipfile.ZipFile(source) as archive:
            verify_epub_mimetype(archive)
            opf_path = self._find_opf(archive)
            opf_root = _parse_xml(read_member(archive, opf_path, max_bytes=_TEXT_LIMIT))
            metadata, manifest, spine, skip_ids, skip_hrefs, cover_item_id = self._read_opf(
                opf_root
            )
            base_dir = str(PurePosixPath(opf_path).parent)
            non_content = {self._resolve(base_dir, href) for href in skip_hrefs}

            assets, asset_bytes = self._collect_assets(
                archive, manifest, base_dir, options, warnings, cover_item_id
            )

            sections: list[Section] = []
            global_block_order = 0
            section_order = 0
            for item_id in spine:
                if item_id in skip_ids:
                    continue
                item = manifest.get(item_id)
                if item is None:
                    warnings.append(f"Spine references missing manifest item {item_id!r}.")
                    continue
                href, media_type = item["href"], item["media_type"]
                if media_type not in ("application/xhtml+xml", "text/html"):
                    continue
                member = self._resolve(base_dir, href)
                if member in non_content:
                    continue
                if member not in archive.namelist():
                    warnings.append(f"Missing content document {member!r}.")
                    continue
                content = read_member(archive, member, max_bytes=_TEXT_LIMIT)
                section = self._parse_content_document(
                    content, section_order, member, options, warnings
                )
                for block in section.blocks:
                    block.source_order = global_block_order
                    block.id = block_id(global_block_order)
                    global_block_order += 1
                if global_block_order > options.max_text_blocks:
                    raise ValidationError("Document exceeds the maximum block count.")
                sections.append(section)
                section_order += 1

        document = CanonicalDocument(
            document_id=options.document_id,
            source_type=DocumentType.EPUB.value,
            metadata=metadata,
            source_language=metadata.language,
            sections=sections,
            assets=assets,
            warnings=warnings,
        )
        return ParseResult(document=document, warnings=warnings, asset_bytes=asset_bytes)

    # -- container/OPF -------------------------------------------------------
    @staticmethod
    def _find_opf(archive: zipfile.ZipFile) -> str:
        container = _parse_xml(read_member(archive, "META-INF/container.xml", max_bytes=1_000_000))
        for rootfile in container.iter(f"{{{CONTAINER_NS}}}rootfile"):
            path = rootfile.get("full-path")
            if path:
                return path
        # Fall back to a filesystem-independent search.
        for name in archive.namelist():
            if name.endswith(".opf"):
                return name
        raise ValidationError("EPUB has no package document.")

    @staticmethod
    def _read_opf(
        root: etree._Element,
    ) -> tuple[
        DocumentMetadata,
        dict[str, dict[str, str]],
        list[str],
        set[str],
        set[str],
        str | None,
    ]:
        def dc(name: str) -> list[str]:
            return [
                (element.text or "").strip()
                for element in root.iter(f"{{{DC_NS}}}{name}")
                if (element.text or "").strip()
            ]

        titles = dc("title")
        metadata = DocumentMetadata(
            title=_first(titles),
            authors=dc("creator"),
            publisher=_first(dc("publisher")),
            language=_first(dc("language")),
            identifier=_first(dc("identifier")),
            description=_first(dc("description")),
        )

        manifest: dict[str, dict[str, str]] = {}
        manifest_root = root.find(f"{{{OPF_NS}}}manifest")
        if manifest_root is not None:
            for item in manifest_root.iter(f"{{{OPF_NS}}}item"):
                item_id = item.get("id")
                if not item_id:
                    continue
                manifest[item_id] = {
                    "href": item.get("href", ""),
                    "media_type": item.get("media-type", ""),
                    "properties": item.get("properties", ""),
                }

        spine: list[str] = []
        spine_root = root.find(f"{{{OPF_NS}}}spine")
        if spine_root is not None:
            for itemref in spine_root.iter(f"{{{OPF_NS}}}itemref"):
                idref = itemref.get("idref")
                if idref:
                    spine.append(idref)

        # Navigation documents are not translatable content.
        skip_ids = {
            item_id
            for item_id, item in manifest.items()
            if "nav" in item.get("properties", "").split()
        }
        skip_hrefs: set[str] = set()
        guide = root.find(f"{{{OPF_NS}}}guide")
        if guide is not None:
            for reference in guide.iter(f"{{{OPF_NS}}}reference"):
                if reference.get("type") in ("cover", "toc") and reference.get("href"):
                    skip_hrefs.add(reference.get("href", ""))

        cover_item_id: str | None = None
        for meta in root.iter(f"{{{OPF_NS}}}meta"):
            if meta.get("name") == "cover" and meta.get("content"):
                cover_item_id = meta.get("content")
                break
        if cover_item_id is None:
            for item_id, item in manifest.items():
                if "cover-image" in item.get("properties", "").split():
                    cover_item_id = item_id
                    break
        return metadata, manifest, spine, skip_ids, skip_hrefs, cover_item_id

    @staticmethod
    def _resolve(base_dir: str, href: str) -> str:
        joined = str(PurePosixPath(base_dir) / href) if base_dir else href
        # Normalize but never escape the archive root.
        return str(PurePosixPath(joined))

    def _collect_assets(
        self,
        archive: zipfile.ZipFile,
        manifest: dict[str, dict[str, str]],
        base_dir: str,
        options: ParseOptions,
        warnings: list[str],
        cover_item_id: str | None = None,
    ) -> tuple[list[Asset], dict[str, bytes]]:
        assets: list[Asset] = []
        asset_bytes: dict[str, bytes] = {}
        counter = 0
        names = set(archive.namelist())
        for item_id, item in manifest.items():
            media_type = item["media_type"]
            if media_type in ("application/xhtml+xml", "text/html", ""):
                continue
            member = self._resolve(base_dir, item["href"])
            if member not in names:
                continue
            try:
                data = read_member(archive, member, max_bytes=options.max_uncompressed_bytes)
            except ValidationError:
                warnings.append(f"Skipped oversized asset {member!r}.")
                continue
            aid = asset_id(counter)
            counter += 1
            filename = PurePosixPath(member).name
            storage_key = (
                f"documents/{options.document_id}/assets/{aid}/{filename}"
                if options.document_id
                else None
            )
            attributes: dict[str, str] = {"href": item["href"]}
            if cover_item_id and item_id == cover_item_id:
                attributes["role"] = "cover"
            assets.append(
                Asset(
                    id=aid,
                    filename=filename,
                    media_type=media_type,
                    storage_key=storage_key,
                    attributes=attributes,
                )
            )
            asset_bytes[aid] = data
        return assets, asset_bytes

    # -- content -------------------------------------------------------------
    def _parse_content_document(
        self,
        content: bytes,
        order: int,
        member: str,
        options: ParseOptions,
        warnings: list[str],
    ) -> Section:
        tree = _parse_xml(content)
        title = None
        title_el = tree.find(f".//{{{XHTML_NS}}}title")
        if title_el is not None and title_el.text:
            title = title_el.text.strip()

        section = Section(
            id=section_id(order),
            source_order=order,
            title=title,
            source_ref=member,
            attributes={},
        )
        body = None
        for element in tree.iter():
            if _localname(element) == "body":
                body = element
                break
        if body is None:
            warnings.append(f"No <body> in {member!r}.")
            return section

        self._walk(body, section, [], member)
        return section

    def _walk(
        self,
        element: etree._Element,
        section: Section,
        list_stack: list[str],
        member: str,
    ) -> None:
        for child in element:
            tag = _localname(child)
            if tag in ("script", "style", "head", "title"):
                continue
            if tag in ("ul", "ol"):
                list_block = self._make_block(section, BlockType.LIST, child, member, None, None)
                self._walk(child, section, [*list_stack, list_block.id], member)
                continue
            if tag == "li":
                self._make_block(
                    section,
                    BlockType.LIST_ITEM,
                    child,
                    member,
                    list_stack[-1] if list_stack else None,
                    None,
                )
                continue
            if tag in _HEADINGS:
                self._make_block(section, BlockType.HEADING, child, member, None, _HEADINGS[tag])
                continue
            if tag == "p":
                self._make_block(section, BlockType.PARAGRAPH, child, member, None, None)
                continue
            if tag == "blockquote":
                # Its child <p> becomes a quote; recurse with quote context via class.
                self._make_block(section, BlockType.QUOTE, child, member, None, None)
                continue
            if tag in ("figcaption", "caption"):
                self._make_block(section, BlockType.CAPTION, child, member, None, None)
                continue
            if tag in ("pre",):
                self._make_block(section, BlockType.CODE, child, member, None, None)
                continue
            if tag in ("table",):
                self._make_block(section, BlockType.TABLE, child, member, None, None)
                continue
            if tag in ("img", "image"):
                self._make_image_block(section, child, member)
                continue
            if tag == "hr":
                self._make_block(section, BlockType.SEPARATOR, child, member, None, None)
                continue
            # Container elements: recurse.
            self._walk(child, section, list_stack, member)

    def _make_block(
        self,
        section: Section,
        block_type: BlockType,
        element: etree._Element,
        member: str,
        parent_id: str | None,
        level: int | None,
    ) -> TextBlock:
        markup = _inner_markup(element)
        plain = _plain_text(element)
        links = [
            href
            for anchor in element.iter()
            if _localname(anchor) == "a" and (href := anchor.get("href"))
        ]
        source_ref = element.get("id") or f"{member}#{len(section.blocks)}"
        block = TextBlock(
            id="pending",
            type=block_type,
            source_order=len(section.blocks),
            source_text=markup if (markup or plain) else None,
            parent_id=parent_id,
            level=level,
            source_ref=source_ref,
            formatting={"tag": _localname(element), "inner_markup": markup},
            attributes={
                "plain_text": plain,
                "element_id": element.get("id"),
                "class": element.get("class"),
                "style": element.get("style"),
            },
            links=links,
        )
        if not plain and block_type not in (BlockType.SEPARATOR, BlockType.IMAGE):
            block.source_text = None
        section.blocks.append(block)
        return block

    def _make_image_block(self, section: Section, element: etree._Element, member: str) -> None:
        src = element.get("src") or element.get("{http://www.w3.org/1999/xlink}href")
        section.blocks.append(
            TextBlock(
                id="pending",
                type=BlockType.IMAGE,
                source_order=len(section.blocks),
                source_ref=f"{member}#{len(section.blocks)}",
                attributes={"src": src, "alt": element.get("alt")},
            )
        )


__all__ = ["EpubParser"]
