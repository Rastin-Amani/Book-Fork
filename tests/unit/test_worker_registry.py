"""Worker liveness registry and operational endpoints."""

from __future__ import annotations

from app.observability.metrics import metrics
from app.repositories.workers import WorkerRepository
from fastapi.testclient import TestClient
from worker.heartbeat import WorkerRegistry


async def test_worker_register_beat_offline(pb, fake_pb) -> None:
    repository = WorkerRepository(pb)
    registry = WorkerRegistry(repository, worker_id="w1", version="0.1.0")
    await registry.register()
    record = await repository.get_by_worker_id("w1")
    assert record is not None
    assert record.status == "running"

    await registry.beat(2)
    record = await repository.get_by_worker_id("w1")
    assert record is not None
    assert record.current_jobs == 2

    await registry.offline()
    record = await repository.get_by_worker_id("w1")
    assert record is not None
    assert record.status == "stopped"


def test_metrics_endpoint_exposes_prometheus_text(client: TestClient) -> None:
    metrics.inc("book_fork_test_counter_total")
    try:
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "book_fork_test_counter_total" in response.text
    finally:
        metrics.reset()


def test_worker_health_reports_unavailable_without_service_credential(
    client: TestClient,
) -> None:
    # The default test settings configure no service credential.
    response = client.get("/health/worker")
    assert response.status_code == 503
    assert response.json()["alive"] is False
