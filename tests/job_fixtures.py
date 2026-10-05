"""In-memory job store, plus fake document engine/repository for worker tests."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.documents.adapters.base import (
    DocumentType,
    ExportResult,
    ParseOptions,
    ParseResult,
)
from app.documents.model import (
    BlockType,
    CanonicalDocument,
    DocumentMetadata,
    Section,
    TextBlock,
)
from app.documents.segmentation.base import Segment
from app.schemas.documents import Document
from app.schemas.translation import (
    TranslationAttempt,
    TranslationJob,
    TranslationSegment,
)

from tests.translation_fixtures import make_plan


def canonical_document() -> CanonicalDocument:
    return CanonicalDocument(
        document_id="doc1",
        source_type="epub",
        metadata=DocumentMetadata(title="Book"),
        sections=[
            Section(
                id="section_000",
                source_order=0,
                blocks=[
                    TextBlock(
                        id="block_0000",
                        type=BlockType.PARAGRAPH,
                        source_order=0,
                        source_text="Hello",
                        attributes={"plain_text": "Hello"},
                    )
                ],
            )
        ],
    )


def make_job(
    *,
    job_id: str = "job1",
    workspace: str = "w1",
    document: str = "doc1",
    status: str = "queued",
    snapshot: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
    **overrides: Any,
) -> TranslationJob:
    return TranslationJob(
        id=job_id,
        workspace=workspace,
        document=document,
        target_language="fa",
        status=status,
        snapshot=dict(snapshot if snapshot is not None else make_plan().snapshot()),
        metadata=dict(metadata or {}),
        **overrides,
    )


class FakeJobStore:
    def __init__(self) -> None:
        self.jobs: dict[str, TranslationJob] = {}
        self.segments: dict[str, TranslationSegment] = {}
        self.attempts: list[TranslationAttempt] = []
        self.events: list[dict[str, Any]] = []
        self.job_updates: list[dict[str, Any]] = []
        self._seq = 0

    def add_job(self, job: TranslationJob) -> TranslationJob:
        self.jobs[job.id] = job
        return job

    def add_segment(
        self,
        job_id: str,
        *,
        text: str = "Hello",
        status: str = "pending",
        translated_text: str | None = None,
    ) -> TranslationSegment:
        self._seq += 1
        segment = TranslationSegment(
            id=f"seg{self._seq}",
            job=job_id,
            document="doc1",
            sequence_index=self._seq,
            source_text=text,
            translated_text=translated_text,
            status=status,
            attempt_count=0,
            metadata={"block_id": "block_0000", "segment_key": f"k{self._seq}"},
        )
        self.segments[segment.id] = segment
        return segment

    async def claim_next(
        self, *, worker_id: str, lease_seconds: int, job_id: str | None = None
    ) -> TranslationJob | None:
        if job_id is not None:
            job = self.jobs.get(job_id)
            if job is None or job.status == "completed":
                return None
        else:
            job = next((j for j in self.jobs.values() if j.status == "queued"), None)
            if job is None:
                return None
        claimed = job.model_copy(
            update={
                "status": "preparing",
                "worker_id": worker_id,
                "lease_id": uuid.uuid4().hex,
                "lease_expires_at": datetime.now(UTC) + timedelta(seconds=lease_seconds),
            }
        )
        self.jobs[job.id] = claimed
        return claimed

    async def get_job(self, job_id: str) -> TranslationJob:
        return self.jobs[job_id]

    async def update_job(self, job_id: str, fields: Mapping[str, Any]) -> TranslationJob:
        self.job_updates.append({"id": job_id, **fields})
        job = self.jobs[job_id].model_copy(update=dict(fields))
        self.jobs[job_id] = job
        return job

    async def heartbeat(self, *, job_id: str, lease_id: str, lease_seconds: int) -> bool:
        job = self.jobs.get(job_id)
        if job is None or job.lease_id != lease_id:
            return False
        self.jobs[job_id] = job.model_copy(
            update={
                "last_heartbeat": datetime.now(UTC),
                "lease_expires_at": datetime.now(UTC) + timedelta(seconds=lease_seconds),
            }
        )
        return True

    async def recover_stale(self) -> int:
        now = datetime.now(UTC)
        count = 0
        for job_id, job in list(self.jobs.items()):
            active = job.status in {
                "preparing",
                "parsing",
                "segmenting",
                "translating",
                "finalizing",
            }
            if active and job.lease_expires_at and job.lease_expires_at < now:
                self.jobs[job_id] = job.model_copy(update={"status": "queued", "lease_id": ""})
                count += 1
        return count

    async def list_segments(self, job_id: str) -> list[TranslationSegment]:
        items = [s for s in self.segments.values() if s.job == job_id]
        return sorted(items, key=lambda s: s.sequence_index)

    async def create_segments(
        self, job_id: str, records: Sequence[Mapping[str, Any]]
    ) -> list[TranslationSegment]:
        if await self.list_segments(job_id):
            return await self.list_segments(job_id)
        created: list[TranslationSegment] = []
        for record in records:
            self._seq += 1
            segment = TranslationSegment.model_validate({"id": f"seg{self._seq}", **record})
            self.segments[segment.id] = segment
            created.append(segment)
        return created

    async def update_segment(
        self, segment_id: str, fields: Mapping[str, Any]
    ) -> TranslationSegment:
        segment = self.segments[segment_id].model_copy(update=dict(fields))
        self.segments[segment_id] = segment
        return segment

    async def attempts_for_segment(self, segment_id: str) -> list[TranslationAttempt]:
        return [a for a in self.attempts if a.segment == segment_id]

    async def create_attempt(self, record: Mapping[str, Any]) -> TranslationAttempt:
        self._seq += 1
        attempt = TranslationAttempt.model_validate({"id": f"att{self._seq}", **record})
        self.attempts.append(attempt)
        return attempt

    async def append_event(
        self,
        job_id: str,
        *,
        type: str,
        message: str | None = None,
        level: str = "info",
        data: Mapping[str, Any] | None = None,
    ) -> None:
        self.events.append({"job": job_id, "type": type, "message": message, "level": level})


class FakeDocumentEngine:
    def __init__(self) -> None:
        self.parsed = 0
        self.exported = 0
        self.segmented = 0

    @asynccontextmanager
    async def materialize(self, storage: Any, key: str) -> AsyncIterator[Path]:
        yield Path("/dev/null")

    async def parse_file(
        self, source: Path, *, document_type: DocumentType, options: ParseOptions
    ) -> ParseResult:
        self.parsed += 1
        return ParseResult(document=canonical_document(), warnings=[], asset_bytes={})

    async def store_assets(self, storage: Any, result: ParseResult, *, document_id: str) -> None:
        return None

    async def store_canonical(
        self, storage: Any, document: CanonicalDocument, *, document_id: str
    ) -> str:
        return f"documents/{document_id}/canonical/v1.json"

    def segment(self, document: CanonicalDocument, config: Any) -> list[Segment]:
        self.segmented += 1
        return [
            Segment(
                id="block_0000#s000",
                block_id="block_0000",
                section_id="section_000",
                index=0,
                text="Hello",
                source_order=0,
                block_type=BlockType.PARAGRAPH,
            )
        ]

    async def export_file(
        self, document: CanonicalDocument, *, document_type: DocumentType, options: Any
    ) -> ExportResult:
        self.exported += 1
        extension = {
            DocumentType.PDF: ".pdf",
            DocumentType.EPUB: ".epub",
        }.get(document_type, ".bin")
        media_type = {
            ".pdf": "application/pdf",
            ".epub": "application/epub+zip",
        }.get(extension, "application/octet-stream")
        path = options.output_dir / f"out{extension}"
        path.write_bytes(b"OUTPUT")
        return ExportResult(path=path, media_type=media_type, extension=extension)

    async def load_canonical(self, storage: Any, key: str) -> CanonicalDocument:
        return canonical_document()


class FakeDocumentRepository:
    def __init__(self, document: Document | None = None) -> None:
        self._document = document or Document(
            id="doc1",
            workspace="w1",
            original_filename="book.epub",
            status="ready",
            created_by="u1",
            document_type="epub",
            storage_key="documents/doc1/source.epub",
        )

    async def get(self, record_id: str, *, token: str | None = None) -> Document:
        return self._document
