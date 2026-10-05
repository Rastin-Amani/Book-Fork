"""PDF parsing.

Extracts a page-ordered, block-level representation from text-based PDFs and
stores enough metadata (page number, bounding box, font size) to support
reflowed output. Scanned pages are flagged as requiring OCR rather than forced
through it.

Structure recovery is important for a readable book. MuPDF often returns a whole
page as a single text block, so blocks are rebuilt here from *lines*:

- spans within a line that are separated by a horizontal gap get a space (words
  in a text layer are frequently glued together);
- runs like ``overratedPlanning``/``TAKEDOWNSIgnore`` are split at
  lower→upper and acronym→Word boundaries;
- a new paragraph starts where a line is indented relative to the page margin;
- a line is a heading when it is mostly **bold** (chapter titles in converted
  ebooks typically differ from the body by weight, not size);
- the first page is rendered as the document cover.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any, ClassVar

import pymupdf

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
from app.exceptions import ValidationError

_LIST_MARKER = re.compile(r"^\s*(?:[-*•‣]|\(?\d{1,3}[.)]|[a-z][.)])\s+")
_GENERIC_HEADINGS = {"CHAPTER", "PART", "SECTION", "CONTENTS"}
_LOWER_UPPER = re.compile(r"(?<=[a-z])(?=[A-Z])")
_ACRONYM_WORD = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")
_WHITESPACE = re.compile(r"\s+")

_BOLD_FLAG = 16
_INDENT = 12
_PARAGRAPH_GAP = 6
_COVER_DPI = 150
_MIN_IMAGE_PT = 8.0
_MIN_IMAGE_PX = 16


def _repair_spacing(text: str) -> str:
    """Normalize spacing and split text layers that omit word breaks."""
    text = text.replace("\xa0", " ")
    text = _LOWER_UPPER.sub(" ", text)
    text = _ACRONYM_WORD.sub(" ", text)
    return _WHITESPACE.sub(" ", text).strip()


def _line_text(line: dict[str, Any]) -> str:
    parts: list[str] = []
    previous_x1: float | None = None
    previous_text = ""
    for span in line.get("spans", []):
        span_text = span.get("text", "")
        if not span_text:
            continue
        x0, x1 = span.get("bbox", (0, 0, 0, 0))[0], span.get("bbox", (0, 0, 0, 0))[2]
        if (
            previous_x1 is not None
            and abs(x0 - previous_x1) > 1.5
            and previous_text[-1:] not in (" ",)
            and span_text[:1] not in (" ",)
        ):
            parts.append(" ")
        parts.append(span_text)
        previous_x1 = x1
        previous_text = span_text
    return _repair_spacing("".join(parts))


def _line_bold_ratio(line: dict[str, Any]) -> float:
    total = 0
    bold = 0
    for span in line.get("spans", []):
        length = len(span.get("text", "") or "")
        total += length
        if span.get("flags", 0) & _BOLD_FLAG:
            bold += length
    return bold / total if total else 0.0


def _page_lines(page: dict[str, Any]) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for block in page.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            text = _line_text(line)
            if not text:
                continue
            bbox = line.get("bbox", (0, 0, 0, 0))
            sizes = [span.get("size", 0.0) for span in line.get("spans", [])]
            lines.append(
                {
                    "text": text,
                    "x0": bbox[0],
                    "y0": bbox[1],
                    "y1": bbox[3],
                    "bold": _line_bold_ratio(line) > 0.6,
                    "size": max(sizes) if sizes else 0.0,
                    "bbox": list(bbox),
                }
            )
    lines.sort(key=lambda item: (round(item["y0"], 1), item["x0"]))
    return lines


def _page_blocks(
    page: dict[str, Any], *, body_size: float, allow_headings: bool = True
) -> list[dict[str, Any]]:
    lines = _page_lines(page)
    if not lines:
        return []
    margin = min(line["x0"] for line in lines)
    blocks: list[dict[str, Any]] = []
    for line in lines:
        indented = line["x0"] > margin + _INDENT
        larger = body_size > 0 and line["size"] >= body_size * 1.35
        is_heading = (line["bold"] or larger) and allow_headings and len(line["text"]) >= 3
        gap = line["y0"] - blocks[-1]["lines"][-1]["y1"] if blocks else 0.0
        if (
            not blocks
            or line["bold"]
            or larger
            or indented
            or blocks[-1]["heading"]
            or gap > _PARAGRAPH_GAP
        ):
            blocks.append({"lines": [line], "heading": is_heading})
        else:
            blocks[-1]["lines"].append(line)
    return blocks


def _allow_headings(page_count: int, page_number: int) -> bool:
    """Page 0 of a multi-page PDF is its cover/title; do not mine it for headings."""
    return page_number > 0 or page_count == 1


def _looks_like_toc(blocks: list[dict[str, Any]]) -> bool:
    """A page dominated by short, single-line entries is a printed contents page."""
    if len(blocks) < 8:
        return False
    single_line = sum(1 for block in blocks if len(block["lines"]) == 1)
    return single_line >= len(blocks) * 0.7


def _body_size(pages: list[dict[str, Any]]) -> float:
    sizes: list[float] = []
    for page in pages:
        for block in page.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    size = span.get("size")
                    if isinstance(size, (int, float)) and size > 0:
                        sizes.append(round(float(size), 1))
    if not sizes:
        return 0.0
    counts = Counter(sizes)
    return min(counts, key=lambda size: (-counts[size], size))


def _document_column(pages: list[dict[str, Any]]) -> tuple[float, float]:
    """Left/right extent of the body text, used to size images relatively."""
    xs0: list[float] = []
    xs1: list[float] = []
    for page in pages:
        for line in _page_lines(page):
            bbox = line["bbox"]
            xs0.append(bbox[0])
            xs1.append(bbox[2])
    if not xs0:
        return (0.0, 1.0)
    return (min(xs0), max(xs1))


def _image_width_pct(width: float, column: tuple[float, float]) -> float:
    """Image width as a percentage of the text column (capped to the column)."""
    column_width = max(column[1] - column[0], 1.0)
    return round(max(5.0, min(100.0, 100.0 * width / column_width)), 1)


def _image_align(bbox: Sequence[float], column: tuple[float, float]) -> str:
    """Horizontal placement of an image within the text column."""
    column_width = max(column[1] - column[0], 1.0)
    left_gap = bbox[0] - column[0]
    right_gap = column[1] - bbox[2]
    if abs(left_gap - right_gap) <= 0.1 * column_width:
        return "center"
    return "left" if left_gap < right_gap else "right"


class PdfParser:
    document_type: ClassVar[DocumentType] = DocumentType.PDF

    def parse(self, source: Path, options: ParseOptions) -> ParseResult:
        warnings: list[str] = []
        asset_bytes: dict[str, bytes] = {}
        try:
            pdf = pymupdf.open(source)
        except Exception as exc:
            raise ValidationError("The PDF could not be opened.") from exc

        try:
            if pdf.page_count > options.max_pdf_pages:
                raise ValidationError("PDF exceeds the maximum page count.")
            metadata = self._metadata(pdf)

            sections: list[Section] = []
            assets: list[Asset] = []
            global_block_order = 0
            asset_counter = 0
            pages = [pdf[index].get_text("dict") for index in range(pdf.page_count)]
            body_size = _body_size(pages)
            column = _document_column(pages)
            xref_assets: dict[int, Asset] = {}
            for page_number, page in enumerate(pages):
                section = Section(
                    id=section_id(page_number),
                    source_order=page_number,
                    section_type="page",
                    source_ref=f"page:{page_number + 1}",
                    attributes={"page_number": page_number + 1},
                )
                if not page.get("blocks"):
                    warnings.append(
                        f"Page {page_number + 1} has no extractable text (OCR required)."
                    )
                    section.attributes["ocr_required"] = True

                raw_blocks = _page_blocks(
                    page,
                    body_size=body_size,
                    allow_headings=_allow_headings(pdf.page_count, page_number),
                )
                if _looks_like_toc(raw_blocks):
                    for raw in raw_blocks:
                        raw["heading"] = False

                # Text and images are interleaved by vertical position so an
                # image stays with the paragraphs it belongs to.
                items: list[tuple[float, float, dict[str, Any]]] = []
                for raw in raw_blocks:
                    first = raw["lines"][0]
                    items.append((first["y0"], first["x0"], {"kind": "text", "raw": raw}))
                if page_number > 0:  # page 1 is rendered as the cover
                    for info in self._image_infos(pdf, page_number, warnings):
                        bbox = info.get("bbox")
                        if not bbox or len(bbox) < 4:
                            continue
                        width = float(bbox[2]) - float(bbox[0])
                        height = float(bbox[3]) - float(bbox[1])
                        pixel_width = float(info.get("width") or 0)
                        pixel_height = float(info.get("height") or 0)
                        if (
                            min(width, height) < _MIN_IMAGE_PT
                            or min(pixel_width, pixel_height) < _MIN_IMAGE_PX
                        ):
                            continue
                        items.append(
                            (
                                float(bbox[1]),
                                float(bbox[0]),
                                {"kind": "image", "info": info, "bbox": bbox},
                            )
                        )
                items.sort(key=lambda item: (round(item[0], 1), item[1]))

                for _y, _x, item in items:
                    if item["kind"] == "text":
                        raw = item["raw"]
                        text = " ".join(line["text"] for line in raw["lines"]).strip()
                        if not text:
                            continue
                        if raw["heading"] and text.strip().upper() not in _GENERIC_HEADINGS:
                            block_type, level = BlockType.HEADING, 1
                        elif _LIST_MARKER.match(text):
                            block_type, level = BlockType.LIST_ITEM, None
                        else:
                            block_type, level = BlockType.PARAGRAPH, None
                        section.blocks.append(
                            TextBlock(
                                id="pending",
                                type=block_type,
                                source_order=global_block_order,
                                source_text=text,
                                level=level,
                                source_ref=f"page:{page_number + 1}#block{len(section.blocks)}",
                                attributes={
                                    "plain_text": text,
                                    "page_number": page_number + 1,
                                    "bbox": raw["lines"][0]["bbox"],
                                    "font_size": max(line["size"] for line in raw["lines"]),
                                },
                            )
                        )
                        global_block_order += 1
                        if global_block_order > options.max_text_blocks:
                            raise ValidationError("Document exceeds the maximum block count.")
                        continue

                    info = item["info"]
                    xref = info.get("xref")
                    if xref is None:
                        continue
                    asset = xref_assets.get(int(xref))
                    if asset is None:
                        stored = self._store_image(pdf, int(xref), asset_counter, options)
                        if stored is None:
                            continue
                        asset, data = stored
                        xref_assets[int(xref)] = asset
                        asset_counter += 1
                        asset_bytes[asset.id] = data
                        assets.append(asset)
                    section.asset_ids.append(asset.id)
                    bbox = item["bbox"]
                    section.blocks.append(
                        TextBlock(
                            id="pending",
                            type=BlockType.IMAGE,
                            source_order=global_block_order,
                            source_text=None,
                            source_ref=f"page:{page_number + 1}#image",
                            attributes={
                                "src": asset.filename,
                                "alt": "",
                                "width_pct": _image_width_pct(
                                    float(bbox[2]) - float(bbox[0]), column
                                ),
                                "align": _image_align(bbox, column),
                                "page_number": page_number + 1,
                                "bbox": [float(value) for value in bbox],
                            },
                        )
                    )
                    global_block_order += 1

                sections.append(section)

            cover = self._cover_asset(pdf, asset_counter, options)
            if cover is not None:
                asset, data = cover
                assets.append(asset)
                asset_bytes[asset.id] = data

            order = 0
            for section in sections:
                for block in section.blocks:
                    block.id = block_id(order)
                    block.source_order = order
                    order += 1

            document = CanonicalDocument(
                document_id=options.document_id,
                source_type=DocumentType.PDF.value,
                metadata=metadata,
                source_language=metadata.language,
                sections=sections,
                assets=assets,
                warnings=warnings,
            )
            return ParseResult(document=document, warnings=warnings, asset_bytes=asset_bytes)
        finally:
            pdf.close()

    # -- helpers -------------------------------------------------------------
    @staticmethod
    def _metadata(pdf: pymupdf.Document) -> DocumentMetadata:
        raw = pdf.metadata or {}
        authors = [a.strip() for a in (raw.get("author") or "").split(";") if a.strip()]
        return DocumentMetadata(
            title=raw.get("title") or None,
            authors=authors,
            publisher=None,
            language=raw.get("language") or None,
            identifier=raw.get("subject") or None,
            description=raw.get("subject") or None,
        )

    @staticmethod
    def _image_infos(pdf: pymupdf.Document, page_number: int, warnings: list[str]) -> list[dict]:
        """Image placements on a page, each with its bbox, xref and pixel size."""
        try:
            return list(pdf[page_number].get_image_info(xrefs=True))
        except Exception:
            warnings.append(f"Could not read images on page {page_number + 1}.")
            return []

    def _store_image(
        self,
        pdf: pymupdf.Document,
        xref: int,
        counter: int,
        options: ParseOptions,
    ) -> tuple[Asset, bytes] | None:
        try:
            extracted = pdf.extract_image(xref)
        except Exception:
            return None
        data = extracted.get("image")
        if not data:
            return None
        extension = extracted.get("ext", "bin")
        aid = asset_id(counter)
        filename = f"image_{counter}.{extension}"
        storage_key = (
            f"documents/{options.document_id}/assets/{aid}/{filename}"
            if options.document_id
            else None
        )
        media_type = f"image/{'jpeg' if extension in ('jpg', 'jpeg') else extension}"
        return (
            Asset(
                id=aid,
                filename=filename,
                media_type=media_type,
                storage_key=storage_key,
                attributes={"xref": xref},
            ),
            data,
        )

    def _cover_asset(
        self, pdf: pymupdf.Document, counter: int, options: ParseOptions
    ) -> tuple[Asset, bytes] | None:
        """Render the first page as the document cover (PDFs have no cover file)."""
        try:
            pixmap = pdf[0].get_pixmap(dpi=_COVER_DPI)
            data = pixmap.tobytes("png")
        except Exception:
            return None
        if not data:
            return None
        aid = asset_id(counter)
        filename = "cover.png"
        storage_key = (
            f"documents/{options.document_id}/assets/{aid}/{filename}"
            if options.document_id
            else None
        )
        return (
            Asset(
                id=aid,
                filename=filename,
                media_type="image/png",
                storage_key=storage_key,
                attributes={"role": "cover"},
            ),
            data,
        )


__all__ = ["PdfParser"]
