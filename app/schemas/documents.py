"""Document and section domain records."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field

from app.schemas.base import Record


class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    DETECTING = "detecting"
    READY = "ready"
    PARSING = "parsing"
    PARSED = "parsed"
    FAILED = "failed"


class SectionType(StrEnum):
    CHAPTER = "chapter"
    PART = "part"
    SECTION = "section"
    FRONT_MATTER = "front_matter"
    BACK_MATTER = "back_matter"
    OTHER = "other"


class Document(Record):
    workspace: str
    original_filename: str
    status: DocumentStatus
    created_by: str
    display_name: str | None = None
    mime_type: str | None = None
    extension: str | None = None
    document_type: str | None = None
    file_size: float | None = None
    checksum: str | None = None
    storage_key: str | None = None
    # Optional until detection runs; user selection overrides detection.
    source_language: str | None = None
    source_locale: str | None = None
    source_script: str | None = None
    source_direction: str | None = None
    detected_language: str | None = None
    detected_confidence: float | None = None
    language_detection: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentSection(Record):
    document: str
    sequence_index: int
    parent: str | None = None
    title: str | None = None
    section_type: SectionType | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
