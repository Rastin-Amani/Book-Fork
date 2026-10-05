"""PocketBase-backed job store: claim, lease, segments, attempts, events."""

from __future__ import annotations

from app.jobs.store import PocketBaseJobStore
from app.repositories.translation import (
    JobEventRepository,
    TranslationAttemptRepository,
    TranslationJobRepository,
    TranslationSegmentRepository,
)


def _store(pb) -> PocketBaseJobStore:
    return PocketBaseJobStore(
        jobs=TranslationJobRepository(pb),
        segments=TranslationSegmentRepository(pb),
        attempts=TranslationAttemptRepository(pb),
        events=JobEventRepository(pb),
    )


def _seed_job(fake_pb, **overrides):
    return fake_pb.seed(
        "translation_jobs",
        {
            "workspace": "w1",
            "document": "doc1",
            "target_language": "fa",
            "status": "queued",
            **overrides,
        },
    )


async def test_claim_sets_lease_and_status(pb, fake_pb) -> None:
    job = _seed_job(fake_pb)
    _seed_job(fake_pb, status="completed")
    store = _store(pb)

    claimed = await store.claim_next(worker_id="w1", lease_seconds=60)
    assert claimed is not None
    assert claimed.id == job["id"]
    assert claimed.status == "preparing"
    assert claimed.worker_id == "w1"
    assert claimed.lease_id


async def test_claim_specific_job_id(pb, fake_pb) -> None:
    job = _seed_job(fake_pb)
    store = _store(pb)
    claimed = await store.claim_next(worker_id="w1", lease_seconds=60, job_id=job["id"])
    assert claimed is not None and claimed.id == job["id"]


async def test_heartbeat_verifies_lease(pb, fake_pb) -> None:
    job = _seed_job(fake_pb)
    store = _store(pb)
    claimed = await store.claim_next(worker_id="w1", lease_seconds=60)
    assert claimed is not None
    assert await store.heartbeat(
        job_id=claimed.id, lease_id=claimed.lease_id or "", lease_seconds=60
    )
    assert not await store.heartbeat(job_id=claimed.id, lease_id="wrong", lease_seconds=60)
    assert not await store.heartbeat(job_id=job["id"], lease_id="", lease_seconds=60)


async def test_segments_are_idempotent(pb, fake_pb) -> None:
    job = _seed_job(fake_pb)
    store = _store(pb)
    records = [
        {
            "job": job["id"],
            "document": "doc1",
            "sequence_index": 0,
            "source_text": "a",
            "status": "pending",
        },
        {
            "job": job["id"],
            "document": "doc1",
            "sequence_index": 1,
            "source_text": "b",
            "status": "pending",
        },
    ]
    created = await store.create_segments(job["id"], records)
    assert len(created) == 2
    again = await store.create_segments(job["id"], records)
    assert len(again) == 2  # no duplicates
    listed = await store.list_segments(job["id"])
    assert [s.source_text for s in listed] == ["a", "b"]


async def test_attempts_and_events(pb, fake_pb) -> None:
    job = _seed_job(fake_pb)
    store = _store(pb)
    created = await store.create_segments(
        job["id"],
        [
            {
                "job": job["id"],
                "document": "doc1",
                "sequence_index": 0,
                "source_text": "a",
                "status": "pending",
            }
        ],
    )
    await store.create_attempt(
        {"segment": created[0].id, "job": job["id"], "attempt_number": 1, "status": "failed"}
    )
    attempts = await store.attempts_for_segment(created[0].id)
    assert len(attempts) == 1 and attempts[0].attempt_number == 1

    await store.append_event(job["id"], type="translating", message="go")
    events = await JobEventRepository(pb).list_for_job(job["id"])
    assert events and events[0].type == "translating"
