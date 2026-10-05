"""Job executor: full pipeline, resume, cancellation, repair, retries."""

from __future__ import annotations

from typing import Any, cast

from app.jobs.config import WorkerSettings
from app.jobs.retry import RetryService, RetrySettings
from app.providers.errors import ProviderError, ProviderErrorCategory
from app.storage.local import LocalStorage
from app.translation.engine import TranslationEngine
from app.translation.plan import RetryPolicy
from worker.job_executor import JobExecutor

from tests.job_fixtures import (
    FakeDocumentEngine,
    FakeDocumentRepository,
    FakeJobStore,
    make_job,
)
from tests.translation_fixtures import FakeProvider, content_for, make_plan, no_sleep


def _settings(**overrides: Any) -> WorkerSettings:
    base: dict[str, Any] = {
        "credits_enabled": False,
        "lease_seconds": 3600,
        "heartbeat_seconds": 3600,
        "poll_interval_seconds": 0.01,
        "retry": RetrySettings(
            max_attempts=2, initial_delay_seconds=0.0, max_delay_seconds=0.0, jitter=0.0
        ),
        "context_repair_enabled": True,
    }
    base.update(overrides)
    return WorkerSettings(**base)


def _executor(
    store: FakeJobStore,
    provider: FakeProvider,
    tmp_path: Any,
    *,
    settings: WorkerSettings | None = None,
    documents: FakeDocumentEngine | None = None,
) -> JobExecutor:
    async def provider_factory(job: Any, plan: Any) -> Any:
        return provider

    return JobExecutor(
        store=store,
        documents=cast("Any", documents or FakeDocumentEngine()),
        policy=cast("Any", None),
        engine=TranslationEngine(sleep=no_sleep()),
        storage=LocalStorage(tmp_path / "store"),
        document_repository=cast("Any", FakeDocumentRepository()),
        provider_factory=provider_factory,
        settings=settings or _settings(),
        retry=RetryService(sleep=no_sleep()),
        ledger=None,
        temp_root=tmp_path / "tmp",
    )


async def _claim(store: FakeJobStore):
    return await store.claim_next(worker_id="w", lease_seconds=3600)


async def test_completes_job_end_to_end(tmp_path: Any) -> None:
    store = FakeJobStore()
    store.add_job(make_job())
    documents = FakeDocumentEngine()
    executor = _executor(store, FakeProvider(), tmp_path, documents=documents)

    job = await _claim(store)
    assert job is not None
    await executor.execute(job)

    final = store.jobs["job1"]
    assert final.status == "completed"
    assert final.progress == 100.0
    assert final.output_storage_key and final.output_checksum
    assert documents.parsed == 1 and documents.segmented == 1 and documents.exported >= 2
    outputs = final.metadata.get("outputs", {})
    assert {"epub", "pdf"} <= set(outputs)
    assert outputs["epub"]["key"].endswith(".epub")
    assert outputs["pdf"]["key"].endswith(".pdf")
    segments = await store.list_segments("job1")
    assert all(s.status == "validated" and s.translated_text for s in segments)
    assert store.attempts


async def test_progress_persists_per_batch(tmp_path: Any) -> None:
    store = FakeJobStore()
    store.add_job(make_job(snapshot=make_plan(batch_size=1).snapshot()))
    for _ in range(3):
        store.add_segment("job1", text="Hello")
    executor = _executor(store, FakeProvider(), tmp_path, documents=FakeDocumentEngine())

    await executor.execute(await _claim(store))

    completed = [
        update["completed_segments"]
        for update in store.job_updates
        if "completed_segments" in update
    ]
    # Progress advances batch by batch, not only after the whole document.
    assert completed[:3] == [1, 2, 3]
    assert store.jobs["job1"].progress == 100.0


async def test_resume_skips_completed_segments(tmp_path: Any) -> None:
    store = FakeJobStore()
    store.add_job(make_job())
    done = store.add_segment("job1", status="validated", translated_text="سلام", text="Done")
    pending = store.add_segment("job1", status="pending", text="Hello")
    documents = FakeDocumentEngine()
    provider = FakeProvider()
    executor = _executor(store, provider, tmp_path, documents=documents)

    await executor.execute(await _claim(store))

    assert documents.parsed == 0  # segments already exist -> no reparse
    assert provider.calls == 1
    assert [s.id for s in provider.requests[0].segments] == [pending.id]
    assert store.segments[done.id].translated_text == "سلام"


async def test_failed_only_retry_mode(tmp_path: Any) -> None:
    store = FakeJobStore()
    store.add_job(make_job(metadata={"retry_mode": "failed_only"}))
    done = store.add_segment("job1", status="validated", translated_text="سلام")
    failed = store.add_segment("job1", status="failed")
    provider = FakeProvider()
    executor = _executor(store, provider, tmp_path)

    await executor.execute(await _claim(store))

    assert [s.id for s in provider.requests[0].segments] == [failed.id]
    assert store.segments[done.id].translated_text == "سلام"
    assert store.jobs["job1"].status == "completed"


async def test_cooperative_cancellation(tmp_path: Any) -> None:
    store = FakeJobStore()
    store.add_job(make_job(cancellation_requested=True))
    executor = _executor(store, FakeProvider(), tmp_path)

    await executor.execute(await _claim(store))

    assert store.jobs["job1"].status == "cancelled"
    assert any(event["type"] == "cancelled" for event in store.events)


async def test_context_too_large_is_repaired(tmp_path: Any) -> None:
    store = FakeJobStore()
    store.add_job(make_job())
    provider = FakeProvider(errors=[ProviderError(ProviderErrorCategory.CONTEXT_TOO_LARGE)])
    executor = _executor(store, provider, tmp_path)

    await executor.execute(await _claim(store))

    assert store.jobs["job1"].status == "completed"
    assert provider.calls == 2  # first fails, repair retries
    assert any(event["type"] == "context_repair" for event in store.events)


async def test_retryable_error_is_retried_by_worker(tmp_path: Any) -> None:
    store = FakeJobStore()
    snapshot = make_plan(
        retry=RetryPolicy(max_attempts=1, base_delay_seconds=0.0, max_delay_seconds=0.0)
    ).snapshot()
    store.add_job(make_job(snapshot=snapshot))
    provider = FakeProvider(errors=[ProviderError(ProviderErrorCategory.RATE_LIMITED)])
    executor = _executor(store, provider, tmp_path)

    await executor.execute(await _claim(store))

    assert store.jobs["job1"].status == "completed"
    assert provider.calls == 2
    assert len(store.attempts) >= 2


async def test_invalid_response_fails_after_attempts(tmp_path: Any) -> None:
    store = FakeJobStore()

    def builder(request: Any) -> Any:
        from app.providers.base import ProviderResponse

        return ProviderResponse(content=content_for([{"segment_id": "zz", "translation": "x"}]))

    store.add_job(make_job())
    executor = _executor(store, FakeProvider(response_builder=builder), tmp_path)

    await executor.execute(await _claim(store))

    assert store.jobs["job1"].status == "failed"
    segments = await store.list_segments("job1")
    assert all(s.status == "failed" for s in segments)
    assert len(store.attempts) == 2  # one attempt per outer retry


async def test_progress_is_computed_from_segments(tmp_path: Any) -> None:
    store = FakeJobStore()
    store.add_job(make_job())
    executor = _executor(store, FakeProvider(), tmp_path)

    await executor.execute(await _claim(store))

    job = store.jobs["job1"]
    assert job.completed_segments == job.total_segments == 1
    assert job.progress == 100.0


async def test_missing_snapshot_fails_cleanly(tmp_path: Any) -> None:
    store = FakeJobStore()
    store.add_job(make_job(snapshot={}))
    executor = _executor(store, FakeProvider(), tmp_path)

    await executor.execute(await _claim(store))

    assert store.jobs["job1"].status == "failed"
    assert store.jobs["job1"].error_code == "configuration_error"
