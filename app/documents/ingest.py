"""Document upload ingestion.

Validates the upload, stores the source immutably and creates the document
record. Source files are never overwritten.
"""

from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.documents.safety import DocumentKind, sha256_bytes, sniff_kind
from app.exceptions import (
    DocumentCorruptedError,
    DocumentTooLargeError,
    DocumentUnsupportedError,
)
from app.repositories.documents import DocumentRepository
from app.schemas.documents import Document
from app.storage.base import Storage

_KIND_TO_TYPE = {DocumentKind.EPUB: "epub", DocumentKind.PDF: "pdf"}


class DocumentIngestService:
    def __init__(
        self,
        repository: DocumentRepository,
        storage: Storage,
        *,
        settings: Settings,
        token: str | None = None,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._settings = settings
        self._token = token

    async def ingest(
        self,
        *,
        workspace_id: str,
        created_by: str,
        filename: str,
        data: bytes,
        content_type: str | None = None,
    ) -> Document:
        if not data:
            raise DocumentCorruptedError("The uploaded file is empty.")
        if len(data) > self._settings.max_request_bytes:
            raise DocumentTooLargeError("The uploaded file exceeds the allowed size.")
        kind = sniff_kind(filename, data[:16])
        document_type = _KIND_TO_TYPE.get(kind)
        if document_type is None:
            raise DocumentUnsupportedError("Only EPUB and PDF documents are supported.")

        extension = Path(filename).suffix.lower().lstrip(".") or document_type
        record = await self._repository.create(
            {
                "workspace": workspace_id,
                "original_filename": Path(filename).name[:500],
                "display_name": Path(filename).stem[:500],
                "extension": extension[:20],
                "document_type": document_type,
                "mime_type": (content_type or "")[:200] or None,
                "file_size": len(data),
                "checksum": sha256_bytes(data),
                "status": "ready",
                "created_by": created_by,
            },
            token=self._token,
        )
        key = f"documents/{record.id}/source.{extension}"
        await self._storage.put(key, data, content_type=content_type)
        return await self._repository.update(record.id, {"storage_key": key}, token=self._token)
