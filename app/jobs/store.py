"""Persistent job store: claiming, leases, segments, attempts and events.

The worker depends on the ``JobStore`` protocol; the PocketBase implementation
below is the durable backend. Tests use an in-memory store.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from app.repositories.base import filter_eq
from app.repositories.translation import (
    JobEventRepository,
    TranslationAttemptRepository,
    TranslationJobRepository,
    TranslationSegmentRepository,
)
from app.schemas.translation import (
    TranslationAttempt,
    TranslationJob,
    TranslationSegment,
)

_ACTIVE_STATUSES = (
    "preparing",
    "parsing",
    "segmenting",
    "translating",
    "finalizing",
    "cancelling",
)


@runtime_checkable
class JobStore(Protocol):
    async def claim_next(
        self, *, worker_id: str, lease_seconds: int, job_id: str | None = None
    ) -> TranslationJob | None: ...

    async def get_job(self, job_id: str) -> TranslationJob: ...

    async def update_job(self, job_id: str, fields: Mapping[str, Any]) -> TranslationJob: ...

    async def heartbeat(self, *, job_id: str, lease_id: str, lease_seconds: int) -> bool: ...

    async def recover_stale(self) -> int: ...

    async def list_segments(self, job_id: str) -> list[TranslationSegment]: ...

    async def create_segments(
        self, job_id: str, records: Sequence[Mapping[str, Any]]
    ) -> list[TranslationSegment]: ...

    async def update_segment(
        self, segment_id: str, fields: Mapping[str, Any]
    ) -> TranslationSegment: ...

    async def attempts_for_segment(self, segment_id: str) -> list[TranslationAttempt]: ...

    async def create_attempt(self, record: Mapping[str, Any]) -> TranslationAttempt: ...

    async def append_event(
        self,
        job_id: str,
        *,
        type: str,
        message: str | None = None,
        level: str = "info",
        data: Mapping[str, Any] | None = None,
    ) -> None: ...


def _now() -> datetime:
    return datetime.now(UTC)


class PocketBaseJobStore:
    """Durable job store backed by the translation repositories."""

    def __init__(
        self,
        *,
        jobs: TranslationJobRepository,
        segments: TranslationSegmentRepository,
        attempts: TranslationAttemptRepository,
        events: JobEventRepository,
        token: str | None = None,
    ) -> None:
        self._jobs = jobs
        self._segments = segments
        self._attempts = attempts
        self._events = events
        self._token = token

    async def claim_next(
        self, *, worker_id: str, lease_seconds: int, job_id: str | None = None
    ) -> TranslationJob | None:
        candidate: TranslationJob | None
        if job_id is not None:
            candidate = await self._jobs.get(job_id, token=self._token)
            if candidate.status == "completed":
                return None
        else:
            candidate = await self._jobs.first(
                filter=filter_eq("status", "queued"), sort="created", token=self._token
            )
            if candidate is None:
                return None

        lease_id = uuid.uuid4().hex
        expires = _now() + timedelta(seconds=lease_seconds)
        claimed = await self._jobs.update(
            candidate.id,
            {
                "status": "preparing",
                "worker_id": worker_id,
                "lease_id": lease_id,
                "lease_expires_at": expires.isoformat(),
                "last_heartbeat": _now().isoformat(),
                # candidate.started_at is a parsed datetime on resume; format it
                # (PocketBase JSON payloads must not contain datetime objects).
                "started_at": (candidate.started_at or _now()).isoformat(),
                "cancellation_requested": False,
            },
            token=self._token,
        )
        # Best-effort verification: if another worker won the race, yield.
        verified = await self._jobs.get(candidate.id, token=self._token)
        if verified.lease_id != lease_id:
            return None
        return claimed

    async def get_job(self, job_id: str) -> TranslationJob:
        return await self._jobs.get(job_id, token=self._token)

    async def update_job(self, job_id: str, fields: Mapping[str, Any]) -> TranslationJob:
        return await self._jobs.update(job_id, dict(fields), token=self._token)

    async def heartbeat(self, *, job_id: str, lease_id: str, lease_seconds: int) -> bool:
        job = await self._jobs.get(job_id, token=self._token)
        if job.lease_id != lease_id or job.status not in _ACTIVE_STATUSES:
            return False
        await self._jobs.update(
            job_id,
            {
                "last_heartbeat": _now().isoformat(),
                "lease_expires_at": (_now() + timedelta(seconds=lease_seconds)).isoformat(),
            },
            token=self._token,
        )
        return True

    async def recover_stale(self) -> int:
        terminal = ("completed", "failed", "cancelled", "queued", "cancelling")
        status_clauses = " && ".join(f'status != "{status}"' for status in terminal)
        stale = await self._jobs.list(
            filter=f'{status_clauses} && lease_expires_at != "" && lease_expires_at < @now',
            per_page=100,
            token=self._token,
        )
        for job in stale:
            await self._jobs.update(
                job.id,
                {"status": "queued", "worker_id": "", "lease_id": "", "lease_expires_at": None},
                token=self._token,
            )
        return len(stale)

    async def list_segments(self, job_id: str) -> list[TranslationSegment]:
        return await self._segments.list_for_job(job_id, token=self._token)

    async def create_segments(
        self, job_id: str, records: Sequence[Mapping[str, Any]]
    ) -> list[TranslationSegment]:
        existing = await self._segments.list_for_job(job_id, token=self._token)
        if existing:
            return existing
        created: list[TranslationSegment] = []
        for record in records:
            created.append(await self._segments.create(dict(record), token=self._token))
        return created

    async def update_segment(
        self, segment_id: str, fields: Mapping[str, Any]
    ) -> TranslationSegment:
        return await self._segments.update(segment_id, dict(fields), token=self._token)

    async def attempts_for_segment(self, segment_id: str) -> list[TranslationAttempt]:
        return await self._attempts.list_for_segment(segment_id, token=self._token)

    async def create_attempt(self, record: Mapping[str, Any]) -> TranslationAttempt:
        return await self._attempts.create(dict(record), token=self._token)

    async def append_event(
        self,
        job_id: str,
        *,
        type: str,
        message: str | None = None,
        level: str = "info",
        data: Mapping[str, Any] | None = None,
    ) -> None:
        await self._events.create(
            {
                "job": job_id,
                "type": type,
                "message": message,
                "level": level,
                "data": dict(data or {}),
            },
            token=self._token,
        )


__all__ = ["JobStore", "PocketBaseJobStore"]
