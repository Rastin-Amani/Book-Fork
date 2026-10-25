"""Entrypoint and worker-slot identity tests."""

from __future__ import annotations


def test_worker_id_env_override(monkeypatch):
    from worker.main import _worker_id

    monkeypatch.setenv("WORKER_ID", "worker-1")
    assert _worker_id() == "worker-1"
    monkeypatch.delenv("WORKER_ID")
    assert _worker_id().startswith("worker-")
