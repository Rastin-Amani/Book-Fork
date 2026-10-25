"""End-to-end HTTP flow: signup/login → upload → choose languages → start job.

Uses the in-memory PocketBase fake and no external provider. The worker pipeline
itself is covered separately in ``test_worker_executor``; here we prove the web
workflow builds a plan snapshot and queues a job.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.repositories.pocketbase import PocketBaseClient
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.documents_fixtures import write_epub
from tests.integration.test_web import FakeAuthProvider


def _seed_policy(fake_pb: Any) -> str:
    fake_pb.seed(
        "languages",
        {"language_code": "en", "name": "English", "direction": "ltr", "enabled": True},
    )
    fake_pb.seed(
        "languages",
        {
            "language_code": "fa",
            "name": "Persian",
            "direction": "rtl",
            "default_locale": "fa-IR",
            "enabled": True,
        },
    )
    provider = fake_pb.seed(
        "providers",
        {"name": "P", "slug": "p", "provider_type": "openai_compatible", "enabled": True},
    )
    connection = fake_pb.seed(
        "provider_connections",
        {
            "workspace": "",
            "provider": provider["id"],
            "name": "Default",
            "auth_type": "api_key",
            "enabled": True,
            "billing_mode": "managed",
        },
    )
    model = fake_pb.seed(
        "provider_models",
        {
            "provider": provider["id"],
            "model_identifier": "m",
            "enabled": True,
            "quality_score": 0.9,
            "input_cost_per_million_tokens": 1.0,
            "output_cost_per_million_tokens": 2.0,
        },
    )
    fake_pb.seed(
        "model_capabilities",
        {"model": model["id"], "source_language": "en", "target_language": "fa", "supported": True},
    )
    template = fake_pb.seed(
        "prompt_templates",
        {"name": "T", "slug": "default-translation", "purpose": "translation", "enabled": True},
    )
    fake_pb.seed(
        "prompt_versions",
        {
            "template": template["id"],
            "version": 1,
            "status": "active",
            "body": "Translate.\\n{{ source_segments }}",
        },
    )
    fake_pb.seed(
        "translation_profiles",
        {
            "name": "Default",
            "quality_mode": "balanced",
            "is_system_default": True,
            "enabled": True,
            "workspace": "",
            "prompt_template": template["id"],
        },
    )
    return str(connection["id"])


def _login(client: TestClient, app: FastAPI, fake_pb: Any) -> str:
    app.state.ctx.pocketbase = PocketBaseClient("http://pb", client=fake_pb.client())
    app.state.ctx.auth = FakeAuthProvider()
    client.get("/login")
    csrf = client.cookies.get("book_fork_csrf") or ""
    client.post(
        "/auth/login",
        data={"identity": "a@b.co", "password": "secret123"},
        headers={"X-CSRF-Token": csrf},
    )
    return csrf


def test_full_upload_to_queued_job(
    client: TestClient, app: FastAPI, fake_pb: Any, tmp_path: Path
) -> None:
    connection_id = _seed_policy(fake_pb)
    csrf = _login(client, app, fake_pb)
    assert client.get("/app").status_code == 200

    epub_bytes = write_epub(tmp_path / "book.epub").read_bytes()
    response = client.post(
        "/app/translations",
        data={
            "source_language": "en",
            "target_language": "fa",
            "connection_id": connection_id,
            "quality_mode": "balanced",
        },
        files={"upload": ("book.epub", epub_bytes, "application/epub+zip")},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200
    assert response.headers["HX-Redirect"].startswith("/app/translations/")

    jobs = list(fake_pb.collections.get("translation_jobs", {}).values())
    assert len(jobs) == 1
    assert jobs[0]["status"] == "queued"
    assert jobs[0]["snapshot"]["target"]["direction"] == "rtl"
    order = jobs[0]["metadata"]["order"]
    assert order["billing_mode"] == "managed"
    assert order["amount"] == 7.0
    assert order["pages"] > 0
    documents = list(fake_pb.collections.get("documents", {}).values())
    assert len(documents) == 1
    assert documents[0]["storage_key"]

    billing = client.get("/app/settings/billing")
    assert billing.status_code == 200
    assert "Book orders" in billing.text
    assert "$7" in billing.text


def test_estimate_renders_for_existing_document(
    client: TestClient, app: FastAPI, fake_pb: Any, tmp_path: Path
) -> None:
    connection_id = _seed_policy(fake_pb)
    csrf = _login(client, app, fake_pb)
    client.get("/app")

    epub_bytes = write_epub(tmp_path / "book.epub").read_bytes()
    upload = client.post(
        "/app/translations",
        data={
            "source_language": "en",
            "target_language": "fa",
            "connection_id": connection_id,
        },
        files={"upload": ("book.epub", epub_bytes, "application/epub+zip")},
        headers={"X-CSRF-Token": csrf},
    )
    assert upload.status_code == 200
    document_id = next(iter(fake_pb.collections["documents"]))

    estimate = client.post(
        "/app/translations/estimate",
        data={
            "document_id": document_id,
            "source_language": "en",
            "target_language": "fa",
            "connection_id": connection_id,
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert estimate.status_code == 200
    assert "Estimated" in estimate.text


def test_upload_rejects_unsupported_type(client: TestClient, app: FastAPI, fake_pb: Any) -> None:
    _seed_policy(fake_pb)
    csrf = _login(client, app, fake_pb)
    client.get("/app")
    response = client.post(
        "/app/translations",
        data={"source_language": "en", "target_language": "fa"},
        files={"upload": ("notes.txt", b"hello", "text/plain")},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 422
