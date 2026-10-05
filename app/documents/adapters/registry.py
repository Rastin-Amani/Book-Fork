"""Adapter selection by document type."""

from __future__ import annotations

from app.documents.adapters.base import (
    DocumentExporter,
    DocumentParser,
    DocumentType,
)
from app.exceptions import ConfigurationError


class AdapterRegistry:
    """Maps document types to parsers and exporters."""

    def __init__(self) -> None:
        self._parsers: dict[DocumentType, DocumentParser] = {}
        self._exporters: dict[DocumentType, DocumentExporter] = {}

    def register_parser(self, parser: DocumentParser) -> None:
        self._parsers[parser.document_type] = parser

    def register_exporter(self, exporter: DocumentExporter) -> None:
        self._exporters[exporter.document_type] = exporter

    def parser_for(self, document_type: DocumentType) -> DocumentParser:
        parser = self._parsers.get(document_type)
        if parser is None:
            raise ConfigurationError(f"No parser registered for {document_type!r}.")
        return parser

    def exporter_for(self, document_type: DocumentType) -> DocumentExporter:
        exporter = self._exporters.get(document_type)
        if exporter is None:
            raise ConfigurationError(f"No exporter registered for {document_type!r}.")
        return exporter

    def supported_parsers(self) -> list[DocumentType]:
        return list(self._parsers)

    def supported_exporters(self) -> list[DocumentType]:
        return list(self._exporters)


def default_registry() -> AdapterRegistry:
    """Registry with the built-in EPUB and PDF adapters."""
    from app.documents.epub.exporter import EpubExporter
    from app.documents.epub.parser import EpubParser
    from app.documents.pdf.exporter import PdfExporter
    from app.documents.pdf.parser import PdfParser

    registry = AdapterRegistry()
    registry.register_parser(EpubParser())
    registry.register_parser(PdfParser())
    registry.register_exporter(EpubExporter())
    registry.register_exporter(PdfExporter())
    return registry
