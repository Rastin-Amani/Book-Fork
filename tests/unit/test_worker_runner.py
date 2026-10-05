"""Worker run loop: claim and execute with bounded concurrency."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, cast

from app.jobs.config import WorkerSettings
from worker.runner import Worker

from tests.job_fixtures import FakeJobStore, make_job


class StubExecutor:
    def __init__(self) -> None:
        self.executed: list[str] = []

    async def execute(self, job) -> None:
        self.executed.append(job.id)


def _settings() -> WorkerSettings:
    return replace(
        WorkerSettings(), max_concurrent_jobs=1, poll_interval_seconds=0.01, lease_seconds=60
    )


async def test_once_executes_one_job() -> None:
    store = FakeJobStore()
    store.add_job(make_job(job_id="job1"))
    store.add_job(make_job(job_id="job2"))
    executor = StubExecutor()
    worker = Worker(store=store, executor=cast("Any", executor), settings=_settings())

    await worker.run(once=True)

    assert executor.executed == ["job1"]


async def test_specific_job_id() -> None:
    store = FakeJobStore()
    store.add_job(make_job(job_id="job1"))
    store.add_job(make_job(job_id="job2"))
    executor = StubExecutor()
    worker = Worker(store=store, executor=cast("Any", executor), settings=_settings())

    await worker.run(job_id="job2")

    assert executor.executed == ["job2"]


async def test_worker_recovers_stale_then_idles() -> None:
    from datetime import UTC, datetime, timedelta

    store = FakeJobStore()
    store.add_job(
        make_job(
            status="translating",
            lease_expires_at=datetime.now(UTC) - timedelta(seconds=5),
        )
    )
    executor = StubExecutor()
    worker = Worker(store=store, executor=cast("Any", executor), settings=_settings())

    await worker.run(once=True)

    # The stale job was recovered to queued and then claimed and executed.
    assert executor.executed == ["job1"]
