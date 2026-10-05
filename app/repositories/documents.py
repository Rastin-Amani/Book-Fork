"""Document and section repositories."""

from __future__ import annotations

from app.repositories.base import PocketBaseRepository, filter_eq
from app.schemas.documents import Document, DocumentSection


class DocumentRepository(PocketBaseRepository[Document]):
    collection = "documents"
    model = Document

    async def list_for_workspace(
        self, workspace_id: str, *, token: str | None = None, per_page: int = 100
    ) -> list[Document]:
        return await self.list(
            filter=filter_eq("workspace", workspace_id),
            sort="-created",
            token=token,
            per_page=per_page,
        )


class DocumentSectionRepository(PocketBaseRepository[DocumentSection]):
    collection = "document_sections"
    model = DocumentSection

    async def list_for_document(
        self, document_id: str, *, token: str | None = None
    ) -> list[DocumentSection]:
        return await self.list(
            filter=filter_eq("document", document_id), sort="sequence_index", token=token
        )
