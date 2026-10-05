"""Per-workspace usage limits (abuse prevention).

Limits are business configuration read from system settings — never hardcoded.
Absent settings mean "unlimited" (an explicit, safe default) except the upload
size ceiling, which falls back to the transport ceiling.

The service only *decides*; callers raise the error. Counts are server-side.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.exceptions import UsageLimitError
from app.repositories.base import escape_filter_value
from app.repositories.documents import DocumentRepository
from app.repositories.translation import TranslationJobRepository
from app.schemas.translation import TranslationJob
from app.settings.service import SettingsService

KEY_MAX_UPLOAD_BYTES = "upload.maximum_file_size"
KEY_UPLOADS_PER_DAY = "limits.uploads_per_day"
KEY_JOBS_PER_DAY = "limits.jobs_per_day"
KEY_CONCURRENT_JOBS = "limits.max_concurrent_jobs_per_user"
KEY_RETRIES_PER_JOB = "limits.retries_per_job"

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
class UsageLimits:
    max_upload_bytes: int | None = None
    uploads_per_day: int | None = None
    jobs_per_day: int | None = None
    max_concurrent_jobs_per_user: int | None = None
    retries_per_job: int | None = None


class LimitService:
    def __init__(
        self,
        *,
        documents: DocumentRepository,
        jobs: TranslationJobRepository,
        settings: SettingsService,
        fallback_upload_bytes: int,
        token: str | None = None,
    ) -> None:
        self._documents = documents
        self._jobs = jobs
        self._settings = settings
        self._fallback_upload_bytes = fallback_upload_bytes
        self._token = token

    async def limits(self) -> UsageLimits:
        max_upload = await self._settings.get(KEY_MAX_UPLOAD_BYTES, self._fallback_upload_bytes)
        return UsageLimits(
            max_upload_bytes=int(max_upload) if max_upload else self._fallback_upload_bytes,
            uploads_per_day=_optional_int(await self._settings.get(KEY_UPLOADS_PER_DAY, None)),
            jobs_per_day=_optional_int(await self._settings.get(KEY_JOBS_PER_DAY, None)),
            max_concurrent_jobs_per_user=_optional_int(
                await self._settings.get(KEY_CONCURRENT_JOBS, None)
            ),
            retries_per_job=_optional_int(await self._settings.get(KEY_RETRIES_PER_JOB, None)),
        )

    async def check_file_size(self, size: int) -> None:
        limits = await self.limits()
        if limits.max_upload_bytes is not None and size > limits.max_upload_bytes:
            raise UsageLimitError("The file exceeds the configured maximum size.")

    async def check_upload(self, workspace_id: str) -> None:
        limits = await self.limits()
        if limits.uploads_per_day is None:
            return
        used = await self._documents.count(
            filter=(
                f'workspace = "{escape_filter_value(workspace_id)}" && created >= "{_day_start()}"'
            ),
            token=self._token,
        )
        if used >= limits.uploads_per_day:
            raise UsageLimitError("The daily upload limit has been reached.")

    async def check_job_create(self, workspace_id: str) -> None:
        limits = await self.limits()
        workspace = escape_filter_value(workspace_id)
        if limits.jobs_per_day is not None:
            used = await self._jobs.count(
                filter=f'workspace = "{workspace}" && created >= "{_day_start()}"',
                token=self._token,
            )
            if used >= limits.jobs_per_day:
                raise UsageLimitError("The daily translation limit has been reached.")
        if limits.max_concurrent_jobs_per_user is not None:
            active = await self._jobs.count(
                filter=f'workspace = "{workspace}" && ({_ACTIVE_JOB_CLAUSES})',
                token=self._token,
            )
            if active >= limits.max_concurrent_jobs_per_user:
                raise UsageLimitError("The concurrent translation limit has been reached.")

    async def check_retry(self, job: TranslationJob) -> None:
        limits = await self.limits()
        if limits.retries_per_job is None:
            return
        used = int((job.metadata or {}).get("retry_count", 0))
        if used >= limits.retries_per_job:
            raise UsageLimitError("The retry limit for this translation has been reached.")


def _optional_int(value: Any) -> int | None:
    if value in (None, "", 0):
        return None
    try:
        parsed = int(value)
    except TypeError, ValueError:
        return None
    return parsed or None


def _day_start() -> str:
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%d 00:00:00.000Z")
