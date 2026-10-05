"""Translation repositories: jobs, segments, attempts, profiles, events."""

from __future__ import annotations

from app.repositories.base import PocketBaseRepository, escape_filter_value, filter_eq
from app.schemas.translation import (
    JobEvent,
    TranslationAttempt,
    TranslationJob,
    TranslationProfile,
    TranslationSegment,
)


class TranslationJobRepository(PocketBaseRepository[TranslationJob]):
    collection = "translation_jobs"
    model = TranslationJob

    async def list_for_workspace(
        self, workspace_id: str, *, token: str | None = None
    ) -> list[TranslationJob]:
        return await self.list(
            filter=filter_eq("workspace", workspace_id), sort="-created", token=token
        )

    async def list_for_document(
        self, document_id: str, *, token: str | None = None
    ) -> list[TranslationJob]:
        return await self.list(
            filter=filter_eq("document", document_id), sort="-created", token=token
        )


class TranslationSegmentRepository(PocketBaseRepository[TranslationSegment]):
    collection = "translation_segments"
    model = TranslationSegment

    async def list_for_job(
        self, job_id: str, *, token: str | None = None
    ) -> list[TranslationSegment]:
        # A book can have thousands of segments; page over all of them.
        return await self.list_all(
            filter=filter_eq("job", job_id), sort="sequence_index", token=token
        )


class TranslationAttemptRepository(PocketBaseRepository[TranslationAttempt]):
    collection = "translation_attempts"
    model = TranslationAttempt

    async def list_for_segment(
        self, segment_id: str, *, token: str | None = None
    ) -> list[TranslationAttempt]:
        return await self.list_all(
            filter=filter_eq("segment", segment_id), sort="attempt_number", token=token
        )

    async def list_for_job(
        self, job_id: str, *, token: str | None = None
    ) -> list[TranslationAttempt]:
        return await self.list_all(filter=filter_eq("job", job_id), sort="created", token=token)


class TranslationProfileRepository(PocketBaseRepository[TranslationProfile]):
    collection = "translation_profiles"
    model = TranslationProfile

    async def get_system_default(self, *, token: str | None = None) -> TranslationProfile | None:
        return await self.first(filter="is_system_default = true", token=token)

    async def get_by_name(
        self, name: str, *, token: str | None = None
    ) -> TranslationProfile | None:
        return await self.first(filter=filter_eq("name", name), token=token)

    async def list_available(
        self, workspace_id: str | None, *, token: str | None = None
    ) -> list[TranslationProfile]:
        if workspace_id:
            clause = f'workspace = "" || workspace = "{escape_filter_value(workspace_id)}"'
        else:
            clause = 'workspace = ""'
        return await self.list(filter=f"{clause} && enabled = true", token=token)


class JobEventRepository(PocketBaseRepository[JobEvent]):
    collection = "job_events"
    model = JobEvent

    async def list_for_job(self, job_id: str, *, token: str | None = None) -> list[JobEvent]:
        return await self.list_all(filter=filter_eq("job", job_id), sort="created", token=token)
