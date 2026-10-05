"""Translation domain records: jobs, segments, attempts, profiles, events."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from app.schemas.base import Record


class JobStatus(StrEnum):
    QUEUED = "queued"
    PREPARING = "preparing"
    PARSING = "parsing"
    SEGMENTING = "segmenting"
    TRANSLATING = "translating"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    CANCELLING = "cancelling"


class SegmentStatus(StrEnum):
    PENDING = "pending"
    TRANSLATING = "translating"
    TRANSLATED = "translated"
    VALIDATING = "validating"
    VALIDATED = "validated"
    FAILED = "failed"
    SKIPPED = "skipped"


class AttemptStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class ValidationStatus(StrEnum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class QualityMode(StrEnum):
    FAST = "fast"
    ECONOMY = "economy"
    BALANCED = "balanced"
    QUALITY = "quality"
    BEST = "best"


class BlockType(StrEnum):
    PARAGRAPH = "paragraph"
    HEADING = "heading"
    LIST_ITEM = "list_item"
    TABLE_CELL = "table_cell"
    QUOTE = "quote"
    CODE = "code"
    CAPTION = "caption"
    OTHER = "other"


class EventLevel(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class TranslationJob(Record):
    workspace: str
    document: str
    target_language: str
    status: JobStatus
    source_language: str | None = None
    source_locale: str | None = None
    target_locale: str | None = None
    profile: str | None = None
    provider_connection: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    quality_mode: QualityMode | None = None
    progress: float | None = None
    total_segments: int | None = None
    completed_segments: int | None = None
    failed_segments: int | None = None
    estimated_credits: float | None = None
    estimated_provider_cost: float | None = None
    actual_provider_cost: float | None = None
    reserved_credits: float | None = None
    actual_credits: float | None = None
    snapshot: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    worker_id: str | None = None
    lease_id: str | None = None
    lease_expires_at: datetime | None = None
    last_heartbeat: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    cancellation_requested: bool = False
    output_storage_key: str | None = None
    output_checksum: str | None = None
    output_mime_type: str | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TranslationSegment(Record):
    job: str
    document: str
    sequence_index: int
    status: SegmentStatus
    section: str | None = None
    paragraph_index: int | None = None
    source_block_type: BlockType | None = None
    source_text: str | None = None
    translated_text: str | None = None
    attempt_count: int | None = None
    last_attempt_at: datetime | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    provider_cost: float | None = None
    credits_used: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TranslationAttempt(Record):
    segment: str
    job: str
    attempt_number: int
    status: AttemptStatus
    provider: str | None = None
    provider_connection: str | None = None
    model: str | None = None
    prompt_template: str | None = None
    prompt_version: str | None = None
    request_started_at: datetime | None = None
    request_completed_at: datetime | None = None
    latency_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    provider_cost: float | None = None
    validation_status: ValidationStatus | None = None
    error_code: str | None = None
    error_message: str | None = None
    response_metadata: dict[str, Any] = Field(default_factory=dict)


class TranslationProfile(Record):
    name: str
    quality_mode: QualityMode
    description: str | None = None
    workspace: str | None = None
    source_language: str | None = None
    target_language: str | None = None
    source_locale: str | None = None
    target_locale: str | None = None
    style: str | None = None
    tone: str | None = None
    domain: str | None = None
    prompt_template: str | None = None
    glossary_ids: list[str] = Field(default_factory=list)
    translation_memory_policy: dict[str, Any] = Field(default_factory=dict)
    segmentation_strategy: dict[str, Any] = Field(default_factory=dict)
    context_strategy: dict[str, Any] = Field(default_factory=dict)
    normalization_pipeline: dict[str, Any] = Field(default_factory=dict)
    validation_profile: dict[str, Any] = Field(default_factory=dict)
    temperature: float | None = None
    batch_size: int | None = None
    context_window_policy: dict[str, Any] = Field(default_factory=dict)
    is_system_default: bool = False
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class JobEvent(Record):
    job: str
    type: str
    message: str | None = None
    level: EventLevel | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = None
