"""Job queue abstraction.

Document translation runs asynchronously and must be resumable. The worker and
the API coordinate through this boundary rather than coupling to a specific
queue/transport. Concrete implementations (PocketBase-backed, Redis, ...) arrive
with the translation engine.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class Job:
    """A unit of background work."""

    id: str
    type: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    status: JobStatus = JobStatus.PENDING
    attempts: int = 0
    max_attempts: int = 1


@runtime_checkable
class JobQueue(Protocol):
    """Minimal resumable queue contract."""

    async def enqueue(self, job_type: str, payload: Mapping[str, Any]) -> str:
        """Persist a new job and return its id."""
        ...

    async def dequeue(self) -> Job | None:
        """Claim the next pending job, or return None when idle."""
        ...

    async def complete(self, job_id: str) -> None:
        """Mark a job succeeded."""
        ...

    async def fail(self, job_id: str, error: str) -> None:
        """Record a failure, allowing retry while attempts remain."""
        ...
