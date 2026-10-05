"""Admin area: authorization, declarative CRUD, prompt and credit operations."""

from __future__ import annotations

from typing import Any

from app.config import Settings
from app.repositories.pocketbase import PocketBaseClient
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.integration.test_web import FakeAuthProvider


def _admin_app(tmp_path: Any) -> FastAPI:
    from app.main import create_app

    settings = Settings(
        _env_file=None,
        app_env="test",
        app_secret_key="test-secret-key",
        encryption_key="test-encryption-key",
        worker_internal_token="test-worker-token",
        storage_local_root=tmp_path / "storage",
        pocketbase_service_credential="svc-token",
        log_level="WARNING",
    )
    return create_app(settings)


def _login(client: TestClient, app: FastAPI, fake_pb: Any) -> None:
    app.state.ctx.pocketbase = PocketBaseClient("http://pb", client=fake_pb.client())
    app.state.ctx.auth = FakeAuthProvider()
    client.get("/login")
    csrf = client.cookies.get("book_fork_csrf")
    client.post(
        "/auth/login",
        data={"identity": "a@b.co", "password": "secret123"},
        headers={"X-CSRF-Token": csrf},
    )


def _csrf(client: TestClient) -> dict[str, str]:
    client.get("/admin")
    return {"X-CSRF-Token": client.cookies.get("book_fork_csrf") or ""}


def _seed_admin(fake_pb: Any) -> None:
    fake_pb.seed(
        "system_settings",
        {"key": "admin.emails", "value": ["a@b.co"], "type": "json"},
    )


def test_admin_pages_require_admin_listing(tmp_path: Any, fake_pb: Any) -> None:
    app = _admin_app(tmp_path)
    with TestClient(app) as client:
        _login(client, app, fake_pb)
        # Non-admin email -> forbidden.
        fake_pb.seed("system_settings", {"key": "admin.emails", "value": [], "type": "json"})
        response = client.get("/admin")
        assert response.status_code == 403


def test_admin_crud_lifecycle(tmp_path: Any, fake_pb: Any) -> None:
    app = _admin_app(tmp_path)
    with TestClient(app) as client:
        _seed_admin(fake_pb)
        _login(client, app, fake_pb)
        headers = _csrf(client)

        assert client.get("/admin").status_code == 200
        assert "Administration" in client.get("/admin").text
        assert client.get("/admin/languages").status_code == 200

        created = client.post(
            "/admin/languages",
            data={"language_code": "xx", "name": "Testish", "direction": "ltr"},
            headers=headers,
        )
        assert created.headers["HX-Redirect"] == "/admin/languages"
        stored = list(fake_pb.collections["languages"].values())
        assert any(record["language_code"] == "xx" for record in stored)
        record_id = next(r["id"] for r in stored if r["language_code"] == "xx")

        updated = client.post(
            f"/admin/languages/{record_id}",
            data={"language_code": "xx", "name": "Testish 2", "direction": "rtl"},
            headers=headers,
        )
        assert updated.status_code == 200
        assert fake_pb.collections["languages"][record_id]["name"] == "Testish 2"

        deleted = client.post(f"/admin/languages/{record_id}/delete", headers=headers)
        assert deleted.status_code == 200
        assert record_id not in fake_pb.collections["languages"]


def test_admin_requires_csrf(tmp_path: Any, fake_pb: Any) -> None:
    app = _admin_app(tmp_path)
    with TestClient(app) as client:
        _seed_admin(fake_pb)
        _login(client, app, fake_pb)
        response = client.post(
            "/admin/languages",
            data={"language_code": "yy", "name": "No CSRF"},
        )
        assert response.status_code == 403


def test_prompt_version_activation(tmp_path: Any, fake_pb: Any) -> None:
    app = _admin_app(tmp_path)
    with TestClient(app) as client:
        _seed_admin(fake_pb)
        template = fake_pb.seed(
            "prompt_templates", {"name": "T", "slug": "t", "purpose": "translation"}
        )
        v1 = fake_pb.seed(
            "prompt_versions",
            {"template": template["id"], "version": 1, "status": "active", "body": "a"},
        )
        v2 = fake_pb.seed(
            "prompt_versions",
            {"template": template["id"], "version": 2, "status": "draft", "body": "b"},
        )
        _login(client, app, fake_pb)
        headers = _csrf(client)

        response = client.post(f"/admin/prompt-versions/{v2['id']}/activate", headers=headers)
        assert response.headers["HX-Redirect"] == "/admin/prompt-versions"
        assert fake_pb.collections["prompt_versions"][v1["id"]]["status"] == "archived"
        assert fake_pb.collections["prompt_versions"][v2["id"]]["status"] == "active"


def test_credit_adjustment_writes_ledger(tmp_path: Any, fake_pb: Any) -> None:
    app = _admin_app(tmp_path)
    with TestClient(app) as client:
        _seed_admin(fake_pb)
        workspace = fake_pb.seed("workspaces", {"name": "W", "slug": "w", "owner": "u1"})
        wallet = fake_pb.seed(
            "credit_wallets",
            {"workspace": workspace["id"], "balance": 0.0, "currency": "credits"},
        )
        _login(client, app, fake_pb)
        headers = _csrf(client)

        response = client.post(
            f"/admin/credit-wallets/{wallet['id']}/adjust",
            data={"amount": "10", "kind": "grant", "reason": "Goodwill"},
            headers=headers,
        )
        assert response.headers["HX-Redirect"].endswith("/ledger")
        assert fake_pb.collections["credit_wallets"][wallet["id"]]["balance"] == 10.0
        transactions = list(fake_pb.collections.get("credit_transactions", {}).values())
        assert len(transactions) == 1
        assert transactions[0]["amount"] == 10.0
        assert transactions[0]["reference"].endswith(":grant")
