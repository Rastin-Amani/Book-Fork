"""Worker run loop with bounded concurrency.

Claims persistent jobs, executes them with a bounded number of concurrent jobs,
recovers stale leases, and shuts down gracefully. No Redis is required.
"""

from __future__ import annotations

import asyncio
import uuid

from app.jobs.config import WorkerSettings
from app.jobs.store import JobStore
from app.logging import get_logger
from app.observability.events import JOB_CLAIMED, emit
from app.observability.metrics import metrics
from app.schemas.translation import TranslationJob

from worker.heartbeat import WorkerRegistry, recover_stale_jobs
from worker.job_executor import JobExecutor

logger = get_logger(__name__)


class Worker:
    def __init__(
        self,
        *,
        store: JobStore,
        executor: JobExecutor,
        settings: WorkerSettings,
        worker_id: str | None = None,
        registry: WorkerRegistry | None = None,
    ) -> None:
        self._store = store
        self._executor = executor
        self._settings = settings
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self._registry = registry

    async def run(
        self,
        *,
        once: bool = False,
        job_id: str | None = None,
        stop: asyncio.Event | None = None,
    ) -> None:
        logger.info("worker_started", worker_id=self.worker_id)
        if self._registry is not None:
            await self._registry.register()
        await recover_stale_jobs(self._store)

        if job_id is not None:
            job = await self._claim(job_id=job_id)
            if job is not None:
                await self._execute(job)
            await self._offline()
            return

        if once:
            job = await self._claim()
            if job is not None:
                await self._execute(job)
            await self._offline()
            return

        stop = stop or asyncio.Event()
        running: set[asyncio.Task[None]] = set()
        while not stop.is_set():
            await recover_stale_jobs(self._store)
            running = {task for task in running if not task.done()}
            for _ in range(max(0, self._settings.max_concurrent_jobs - len(running))):
                job = await self._claim()
                if job is None:
                    break
                running.add(asyncio.create_task(self._execute(job)))
            metrics.set("book_fork_active_jobs", len(running))
            if self._registry is not None:
                await self._registry.beat(len(running))
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._settings.poll_interval_seconds)
            except TimeoutError:
                continue
        if running:
            await asyncio.gather(*running, return_exceptions=True)
        await self._offline()
        logger.info("worker_stopped", worker_id=self.worker_id)

    async def _offline(self) -> None:
        if self._registry is not None:
            await self._registry.offline()

    async def _claim(self, *, job_id: str | None = None) -> TranslationJob | None:
        job = await self._store.claim_next(
            worker_id=self.worker_id,
            lease_seconds=self._settings.lease_seconds,
            job_id=job_id,
        )
        if job is not None:
            metrics.inc("book_fork_jobs_claimed_total")
            emit(JOB_CLAIMED, job_id=job.id, worker_id=self.worker_id)
        return job

    async def _execute(self, job: TranslationJob) -> None:
        try:
            await self._executor.execute(job)
        except Exception as exc:
            logger.exception("job_task_crashed", job_id=job.id, error=type(exc).__name__)
