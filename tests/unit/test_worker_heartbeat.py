"""Lease heartbeats and stale-job recovery."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from worker.heartbeat import LeaseHeartbeat, recover_stale_jobs

from tests.job_fixtures import FakeJobStore, make_job


async def test_stale_job_is_recovered() -> None:
    store = FakeJobStore()
    store.add_job(
        make_job(
            status="translating",
            lease_id="lease-1",
            lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    )
    recovered = await recover_stale_jobs(store)
    assert recovered == 1
    assert store.jobs["job1"].status == "queued"
    assert store.jobs["job1"].lease_id == ""


async def test_live_lease_is_not_recovered() -> None:
    store = FakeJobStore()
    store.add_job(
        make_job(
            status="translating",
            lease_id="lease-1",
            lease_expires_at=datetime.now(UTC) + timedelta(seconds=600),
        )
    )
    assert await recover_stale_jobs(store) == 0


async def test_heartbeat_refreshes_lease() -> None:
    store = FakeJobStore()
    job = store.add_job(make_job(status="translating", lease_id="lease-1"))
    async with LeaseHeartbeat(
        store=store,
        job_id=job.id,
        lease_id="lease-1",
        lease_seconds=600,
        interval_seconds=0.01,
    ) as heartbeat:
        import asyncio

        await asyncio.sleep(0.05)
        assert heartbeat.lost is False
    assert store.jobs["job1"].lease_id == "lease-1"


async def test_heartbeat_detects_lost_lease() -> None:
    store = FakeJobStore()
    store.add_job(make_job(status="translating", lease_id="other"))
    async with LeaseHeartbeat(
        store=store,
        job_id="job1",
        lease_id="mine",
        lease_seconds=600,
        interval_seconds=0.01,
    ) as heartbeat:
        import asyncio

        await asyncio.sleep(0.05)
        assert heartbeat.lost is True
