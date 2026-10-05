"""Configurable data retention.

Nothing is deleted without an explicit retention window in system settings; an
absent setting means "keep". The sweep is safe to run repeatedly and reports what
it removed. It never touches records referenced by an active job.

Intended to run as a scheduled/periodic maintenance task (see
``scripts/retention.py``), not on the request path.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import anyio

from app.logging import get_logger
from app.observability.events import RETENTION_SWEEP, emit
from app.repositories.base import escape_filter_value
from app.repositories.documents import DocumentRepository
from app.repositories.translation import (
    JobEventRepository,
    TranslationAttemptRepository,
    TranslationJobRepository,
    TranslationSegmentRepository,
)
from app.settings.service import SettingsService
from app.storage.base import Storage

logger = get_logger(__name__)

KEY_SOURCE_DOCUMENTS_DAYS = "retention.source_documents_days"
KEY_OUTPUT_DOCUMENTS_DAYS = "retention.output_documents_days"
KEY_FAILED_JOBS_DAYS = "retention.failed_jobs_days"
KEY_ATTEMPTS_DAYS = "retention.translation_attempts_days"
KEY_JOB_EVENTS_DAYS = "retention.job_events_days"
KEY_TEMP_FILES_HOURS = "retention.temp_files_hours"

_ACTIVE_JOB_CLAUSES = " || ".join(
    f'status = "{status}"'
    for status in (
        "queued",
        "preparing",
        "parsing",
        "segmenting",
        "translating",
        "finalizing",
        "cancelling",
    )
)


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    source_documents_days: int | None = None
    output_documents_days: int | None = None
    failed_jobs_days: int | None = None
    attempts_days: int | None = None
    job_events_days: int | None = None
    temp_files_hours: int | None = None


@dataclass(slots=True)
class RetentionReport:
    documents_deleted: int = 0
    jobs_deleted: int = 0
    attempts_deleted: int = 0
    events_deleted: int = 0
    temp_files_deleted: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "documents_deleted": self.documents_deleted,
            "jobs_deleted": self.jobs_deleted,
            "attempts_deleted": self.attempts_deleted,
            "events_deleted": self.events_deleted,
            "temp_files_deleted": self.temp_files_deleted,
        }


class RetentionService:
    def __init__(
        self,
        *,
        documents: DocumentRepository,
        jobs: TranslationJobRepository,
        segments: TranslationSegmentRepository,
        attempts: TranslationAttemptRepository,
        events: JobEventRepository,
        storage: Storage,
        settings: SettingsService,
        temp_root: Path | None = None,
        token: str | None = None,
    ) -> None:
        self._documents = documents
        self._jobs = jobs
        self._segments = segments
        self._attempts = attempts
        self._events = events
        self._storage = storage
        self._settings = settings
        self._temp_root = temp_root
        self._token = token

    async def policy(self) -> RetentionPolicy:
        return RetentionPolicy(
            source_documents_days=_optional_int(
                await self._settings.get(KEY_SOURCE_DOCUMENTS_DAYS, None)
            ),
            output_documents_days=_optional_int(
                await self._settings.get(KEY_OUTPUT_DOCUMENTS_DAYS, None)
            ),
            failed_jobs_days=_optional_int(await self._settings.get(KEY_FAILED_JOBS_DAYS, None)),
            attempts_days=_optional_int(await self._settings.get(KEY_ATTEMPTS_DAYS, None)),
            job_events_days=_optional_int(await self._settings.get(KEY_JOB_EVENTS_DAYS, None)),
            temp_files_hours=_optional_int(await self._settings.get(KEY_TEMP_FILES_HOURS, None)),
        )

    async def run(self) -> RetentionReport:
        policy = await self.policy()
        report = RetentionReport()
        await self._sweep_documents(policy, report)
        await self._sweep_jobs(policy, report)
        await self._sweep_attempts(policy, report)
        await self._sweep_events(policy, report)
        await self._sweep_temp_files(policy, report)
        emit(RETENTION_SWEEP, **report.as_dict())
        return report

    async def _sweep_documents(self, policy: RetentionPolicy, report: RetentionReport) -> None:
        if policy.source_documents_days is None:
            return
        cutoff = _cutoff(days=policy.source_documents_days)
        status_clause = 'status = "ready" || status = "parsed" || status = "failed"'
        candidates = await self._documents.list(
            filter=f'created < "{cutoff}" && ({status_clause})',
            per_page=500,
            token=self._token,
        )
        for document in candidates:
            active = await self._jobs.count(
                filter=(
                    f'document = "{escape_filter_value(document.id)}" && ({_ACTIVE_JOB_CLAUSES})'
                ),
                token=self._token,
            )
            if active:
                continue
            for key in filter(
                None, [document.storage_key, f"documents/{document.id}/canonical/v1.json"]
            ):
                await self._delete_object(key)
            await self._documents.delete(document.id, token=self._token)
            report.documents_deleted += 1

    async def _sweep_jobs(self, policy: RetentionPolicy, report: RetentionReport) -> None:
        if policy.failed_jobs_days is None:
            return
        cutoff = _cutoff(days=policy.failed_jobs_days)
        candidates = await self._jobs.list(
            filter=f'created < "{cutoff}" && (status = "failed" || status = "cancelled")',
            per_page=500,
            token=self._token,
        )
        for job in candidates:
            for segment in await self._segments.list_for_job(job.id, token=self._token):
                await self._segments.delete(segment.id, token=self._token)
            for attempt in await self._attempts.list_for_job(job.id, token=self._token):
                await self._attempts.delete(attempt.id, token=self._token)
            for event in await self._events.list_for_job(job.id, token=self._token):
                await self._events.delete(event.id, token=self._token)
            if job.output_storage_key:
                await self._delete_object(job.output_storage_key)
            await self._jobs.delete(job.id, token=self._token)
            report.jobs_deleted += 1

    async def _sweep_attempts(self, policy: RetentionPolicy, report: RetentionReport) -> None:
        if policy.attempts_days is None:
            return
        cutoff = _cutoff(days=policy.attempts_days)
        candidates = await self._attempts.list(
            filter=f'created < "{cutoff}"', per_page=500, token=self._token
        )
        for attempt in candidates:
            await self._attempts.delete(attempt.id, token=self._token)
            report.attempts_deleted += 1

    async def _sweep_events(self, policy: RetentionPolicy, report: RetentionReport) -> None:
        if policy.job_events_days is None:
            return
        cutoff = _cutoff(days=policy.job_events_days)
        candidates = await self._events.list(
            filter=f'created < "{cutoff}"', per_page=500, token=self._token
        )
        for event in candidates:
            await self._events.delete(event.id, token=self._token)
            report.events_deleted += 1

    async def _sweep_temp_files(self, policy: RetentionPolicy, report: RetentionReport) -> None:
        if policy.temp_files_hours is None or self._temp_root is None:
            return
        root = Path(self._temp_root)
        threshold = time.time() - policy.temp_files_hours * 3600
        report.temp_files_deleted += await anyio.to_thread.run_sync(
            _cleanup_temp_files, root, threshold
        )

    async def _delete_object(self, key: str) -> None:
        try:
            await self._storage.delete(key)
        except Exception as exc:  # pragma: no cover - storage races
            logger.warning("retention_storage_delete_failed", key=key, error=type(exc).__name__)


def _cleanup_temp_files(root: Path, threshold: float) -> int:
    """Blocking temp-file cleanup run off the event loop."""
    if not root.exists():
        return 0
    removed = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            if path.stat().st_mtime < threshold:
                path.unlink(missing_ok=True)
                removed += 1
        except OSError as exc:  # pragma: no cover - filesystem races
            logger.warning("temp_cleanup_failed", path=str(path), error=type(exc).__name__)
    return removed


def _cutoff(*, days: int) -> str:
    moment = datetime.now(UTC) - timedelta(days=max(0, days))
    return moment.strftime("%Y-%m-%d %H:%M:%S.000Z")


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except TypeError, ValueError:
        return None
    return parsed if parsed > 0 else None
