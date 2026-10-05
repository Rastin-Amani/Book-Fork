"""Job lease heartbeats and stale-job recovery.

A live worker refreshes its lease periodically. If it dies, the lease expires
and the recovery routine returns the job to ``queued`` so another run can pick it
up — without corrupting credit accounting.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import socket
from datetime import UTC, datetime

from app.jobs.store import JobStore
from app.logging import get_logger
from app.repositories.workers import WorkerRepository

logger = get_logger(__name__)


class LeaseHeartbeat:
    """Refreshes a job lease while a job is executing."""

    def __init__(
        self,
        *,
        store: JobStore,
        job_id: str,
        lease_id: str,
        lease_seconds: int,
        interval_seconds: float,
    ) -> None:
        self._store = store
        self._job_id = job_id
        self._lease_id = lease_id
        self._lease_seconds = lease_seconds
        self._interval = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self.lost = False

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            ok = await self._store.heartbeat(
                job_id=self._job_id, lease_id=self._lease_id, lease_seconds=self._lease_seconds
            )
            if not ok:
                self.lost = True
                logger.warning("lease_lost", job_id=self._job_id)
                return

    async def __aenter__(self) -> LeaseHeartbeat:
        self._task = asyncio.create_task(self._run())
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task


async def recover_stale_jobs(store: JobStore) -> int:
    try:
        recovered = await store.recover_stale()
    except Exception as exc:
        logger.warning("stale_recovery_failed", error=type(exc).__name__)
        return 0
    if recovered:
        logger.info("stale_jobs_recovered", count=recovered)
    return recovered


class WorkerRegistry:
    """Persists worker liveness so operators can distinguish worker from process."""

    def __init__(
        self,
        repository: WorkerRepository,
        *,
        worker_id: str,
        version: str | None = None,
        token: str | None = None,
    ) -> None:
        self._repository = repository
        self._worker_id = worker_id
        self._version = version
        self._token = token

    async def register(self) -> None:
        now = datetime.now(UTC).isoformat()
        payload = {
            "worker_id": self._worker_id,
            "host": socket.gethostname(),
            "pid": os.getpid(),
            "status": "running",
            "version": self._version,
            "current_jobs": 0,
            "started_at": now,
            "last_heartbeat": now,
        }
        try:
            existing = await self._repository.get_by_worker_id(self._worker_id, token=self._token)
            if existing is None:
                await self._repository.create(payload, token=self._token)
            else:
                await self._repository.update(existing.id, payload, token=self._token)
        except Exception as exc:  # pragma: no cover - operational resilience
            logger.warning("worker_register_failed", error=type(exc).__name__)

    async def beat(self, current_jobs: int) -> None:
        try:
            existing = await self._repository.get_by_worker_id(self._worker_id, token=self._token)
            if existing is None:
                await self.register()
                return
            await self._repository.update(
                existing.id,
                {
                    "status": "running",
                    "current_jobs": current_jobs,
                    "last_heartbeat": datetime.now(UTC).isoformat(),
                },
                token=self._token,
            )
        except Exception as exc:  # pragma: no cover - operational resilience
            logger.warning("worker_heartbeat_failed", error=type(exc).__name__)

    async def offline(self) -> None:
        try:
            existing = await self._repository.get_by_worker_id(self._worker_id, token=self._token)
            if existing is not None:
                await self._repository.update(existing.id, {"status": "stopped"}, token=self._token)
        except Exception as exc:  # pragma: no cover - shutdown best effort
            logger.warning("worker_offline_mark_failed", error=type(exc).__name__)
