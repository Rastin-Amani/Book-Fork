"""Document adapter interfaces.

Parsers convert a source file into the canonical model; exporters render the
canonical model back to an output format. Everything downstream of adapters is
format-agnostic.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import ClassVar, Protocol, runtime_checkable

from app.documents.model import Asset, CanonicalDocument


class DocumentType(StrEnum):
    EPUB = "epub"
    PDF = "pdf"
    TXT = "txt"


@dataclass(slots=True)
class ParseOptions:
    """Limits and ambient context for parsing."""

    document_id: str | None = None
    max_uncompressed_bytes: int = 500 * 1024 * 1024
    max_archive_entries: int = 5000
    max_compression_ratio: float = 200.0
    max_text_blocks: int = 200_000
    max_pdf_pages: int = 5000


@dataclass(slots=True)
class ParseResult:
    document: CanonicalDocument
    warnings: list[str] = field(default_factory=list)
    asset_bytes: dict[str, bytes] = field(default_factory=dict)


AssetResolver = Callable[[Asset], bytes]


@dataclass(slots=True)
class ExportOptions:
    target_language: str | None = None
    target_direction: str = "ltr"
    target_script: str | None = None
    render_backend: str = "pymupdf"
    document_title: str | None = None
    page_size: str = "a5"
    asset_resolver: AssetResolver | None = None
    font_dir: str | None = None
    output_dir: Path | None = None


@dataclass(slots=True)
class ExportResult:
    path: Path
    media_type: str
    extension: str


@runtime_checkable
class DocumentParser(Protocol):
    document_type: ClassVar[DocumentType]

    def parse(self, source: Path, options: ParseOptions) -> ParseResult:
        """Parse ``source`` into the canonical model (CPU-bound; run in a thread)."""
        ...


@runtime_checkable
class DocumentExporter(Protocol):
    document_type: ClassVar[DocumentType]

    def export(self, document: CanonicalDocument, options: ExportOptions) -> ExportResult:
        """Render the canonical model to an output file."""
        ...
