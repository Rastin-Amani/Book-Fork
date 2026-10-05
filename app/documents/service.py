"""Document engine orchestration.

Wires adapters, segmentation, placeholder protection and storage together. It is
LLM-agnostic: it prepares protected segments and can restore translations, but
knows nothing about providers.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import anyio

from app.documents.adapters.base import (
    DocumentType,
    ExportOptions,
    ExportResult,
    ParseOptions,
    ParseResult,
)
from app.documents.adapters.registry import AdapterRegistry, default_registry
from app.documents.model import CanonicalDocument
from app.documents.ocr.base import NullOcrProvider, OcrProvider
from app.documents.placeholders import PlaceholderProtector, ProtectedText
from app.documents.safety import DocumentKind, safe_temp_dir, sniff_kind
from app.documents.segmentation.base import (
    Segment,
    SegmentationConfig,
    Segmenter,
)
from app.documents.segmentation.strategies import build_segmenter
from app.documents.serialization import (
    canonical_storage_key,
    from_json_bytes,
    to_json_bytes,
)
from app.exceptions import ValidationError
from app.storage.base import Storage, StoredObject

_KIND_TO_TYPE = {
    DocumentKind.EPUB: DocumentType.EPUB,
    DocumentKind.PDF: DocumentType.PDF,
}


@dataclass(slots=True)
class ProtectedSegment:
    """A segment plus its placeholder-protected text and mapping."""

    segment: Segment
    protected: ProtectedText


class DocumentEngine:
    def __init__(
        self,
        *,
        registry: AdapterRegistry | None = None,
        protector: PlaceholderProtector | None = None,
        ocr: OcrProvider | None = None,
        temp_root: Path | None = None,
    ) -> None:
        self._registry = registry or default_registry()
        self._protector = protector or PlaceholderProtector()
        self._ocr = ocr or NullOcrProvider()
        self._temp_root = temp_root

    # -- type detection ------------------------------------------------------
    @staticmethod
    def detect_type(filename: str, header: bytes) -> DocumentType:
        kind = sniff_kind(filename, header)
        document_type = _KIND_TO_TYPE.get(kind)
        if document_type is None:
            raise ValidationError("Unsupported document type.")
        return document_type

    # -- parsing / exporting -------------------------------------------------
    async def parse_file(
        self, source: Path, *, document_type: DocumentType, options: ParseOptions
    ) -> ParseResult:
        parser = self._registry.parser_for(document_type)
        return await anyio.to_thread.run_sync(parser.parse, source, options)

    async def export_file(
        self,
        document: CanonicalDocument,
        *,
        document_type: DocumentType,
        options: ExportOptions,
    ) -> ExportResult:
        exporter = self._registry.exporter_for(document_type)
        return await anyio.to_thread.run_sync(exporter.export, document, options)

    # -- segmentation / protection ------------------------------------------
    def segment(self, document: CanonicalDocument, config: SegmentationConfig) -> list[Segment]:
        segmenter: Segmenter = build_segmenter(config.strategy)
        return segmenter.segment(document, config)

    def protect(self, segments: list[Segment]) -> list[ProtectedSegment]:
        return [
            ProtectedSegment(segment=segment, protected=self._protector.protect(segment.text))
            for segment in segments
        ]

    def restore(self, protected: ProtectedText, translated: str) -> str:
        return self._protector.restore(translated, protected.mapping)

    # -- storage -------------------------------------------------------------
    @asynccontextmanager
    async def materialize(self, storage: Storage, key: str) -> AsyncIterator[Path]:
        """Stream a storage object to a managed temp file for parsing."""
        with safe_temp_dir(base=self._temp_root) as tmp:
            target = tmp / "source.bin"
            with target.open("wb") as handle:
                async for chunk in storage.stream(key):
                    handle.write(chunk)
            yield target

    async def store_source(
        self,
        storage: Storage,
        key: str,
        data: bytes | AsyncIterator[bytes],
        *,
        content_type: str | None = None,
    ) -> StoredObject:
        return await storage.put(key, data, content_type=content_type)

    async def store_assets(
        self, storage: Storage, result: ParseResult, *, document_id: str
    ) -> None:
        for asset in result.document.assets:
            data = result.asset_bytes.get(asset.id)
            if data is None or asset.storage_key is None:
                continue
            await storage.put(asset.storage_key, data, content_type=asset.media_type)

    async def store_canonical(
        self, storage: Storage, document: CanonicalDocument, *, document_id: str
    ) -> str:
        key = canonical_storage_key(document_id)
        await storage.put(key, to_json_bytes(document), content_type="application/json")
        return key

    async def load_canonical(self, storage: Storage, key: str) -> CanonicalDocument:
        return from_json_bytes(await storage.read(key))


__all__ = ["DocumentEngine", "ProtectedSegment"]
