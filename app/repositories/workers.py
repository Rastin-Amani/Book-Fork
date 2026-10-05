"""User and worker repositories (administrative / operational records)."""

from __future__ import annotations

from pydantic import Field

from app.repositories.base import PocketBaseRepository, filter_eq
from app.schemas.base import Record


class UserRecord(Record):
    email: str | None = None
    name: str | None = None
    verified: bool = False


class WorkerRecord(Record):
    worker_id: str
    host: str | None = None
    pid: int | None = None
    status: str | None = None
    version: str | None = None
    current_jobs: int | None = None
    started_at: str | None = None
    last_heartbeat: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class UserRepository(PocketBaseRepository[UserRecord]):
    collection = "users"
    model = UserRecord

    async def get_by_email(self, email: str, *, token: str | None = None) -> UserRecord | None:
        return await self.first(filter=filter_eq("email", email), token=token)


class WorkerRepository(PocketBaseRepository[WorkerRecord]):
    collection = "workers"
    model = WorkerRecord

    async def get_by_worker_id(
        self, worker_id: str, *, token: str | None = None
    ) -> WorkerRecord | None:
        return await self.first(filter=filter_eq("worker_id", worker_id), token=token)
