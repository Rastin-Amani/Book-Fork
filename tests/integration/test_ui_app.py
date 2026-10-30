"""Authenticated UI routes render against a fake PocketBase (hermetic)."""

from __future__ import annotations

from typing import Any

from app.repositories.pocketbase import PocketBaseClient
from fastapi.testclient import TestClient

from tests.integration.test_web import FakeAuthProvider


def _login(client: TestClient, app: Any, fake_pb: Any) -> None:
    app.state.ctx.pocketbase = PocketBaseClient("http://pb", client=fake_pb.client())
    app.state.ctx.auth = FakeAuthProvider()
    client.get("/login")
    response = client.get(
        "/auth/oauth2/callback?code=good-code&state=st-google", follow_redirects=False
    )
    assert response.headers["location"] == "/app"


def _seed_languages(fake_pb: Any) -> None:
    for code, name, direction, script in [
        ("en", "English", "ltr", "Latn"),
        ("fa", "Persian", "rtl", "Arab"),
    ]:
        fake_pb.seed(
            "languages",
            {
                "language_code": code,
                "name": name,
                "direction": direction,
                "script_code": script,
                "default_locale": code,
                "enabled": True,
                "popular": True,
            },
        )


def test_dashboard_bootstraps_workspace_and_renders(
    client: TestClient, app: Any, fake_pb: Any
) -> None:
    _seed_languages(fake_pb)
    _login(client, app, fake_pb)

    response = client.get("/app")
    assert response.status_code == 200
    assert "Dashboard" in response.text
    assert "No translations yet" in response.text
    assert len(fake_pb.collections.get("workspaces", {})) == 1
    assert len(fake_pb.collections.get("workspace_members", {})) == 1


def test_new_translation_form_lists_languages(client: TestClient, app: Any, fake_pb: Any) -> None:
    _seed_languages(fake_pb)
    _login(client, app, fake_pb)

    response = client.get("/app/translations/new")
    assert response.status_code == 200
    assert "New translation" in response.text
    assert "Persian" in response.text


def test_htmx_partial_rendering_for_app_content(client: TestClient, app: Any, fake_pb: Any) -> None:
    _seed_languages(fake_pb)
    _login(client, app, fake_pb)

    full = client.get("/app")
    assert "<!doctype html>" in full.text.lower()

    partial = client.get("/app", headers={"HX-Request": "true"})
    assert "<!doctype html>" not in partial.text.lower()
    assert '<main id="app-content"' in partial.text


def _seed_connection(fake_pb: Any, workspace_id: str, name: str = "Mine") -> dict[str, Any]:
    provider = fake_pb.seed(
        "providers",
        {"name": "P", "slug": "p", "provider_type": "openai_compatible", "enabled": True},
    )
    return fake_pb.seed(
        "provider_connections",
        {
            "workspace": workspace_id,
            "provider": provider["id"],
            "name": name,
            "auth_type": "api_key",
            "enabled": True,
            "billing_mode": "own_api",
        },
    )


def test_provider_credential_rotation_is_scoped_and_validated(
    client: TestClient, app: Any, fake_pb: Any
) -> None:
    _seed_languages(fake_pb)
    _login(client, app, fake_pb)
    client.get("/app")
    workspace = next(iter(fake_pb.collections["workspaces"].values()))
    connection = _seed_connection(fake_pb, workspace["id"])
    csrf = client.cookies.get("book_fork_csrf") or ""

    response = client.post(
        f"/app/providers/{connection['id']}/credential",
        data={"api_key": "sk-new-secret"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200
    assert 'id="provider-' + connection["id"] + '"' in response.text
    stored = list(fake_pb.collections["provider_credentials"].values())
    assert len(stored) == 1
    assert stored[0]["connection"] == connection["id"]
    assert "sk-new-secret" not in stored[0]["encrypted_credential"]
    assert stored[0]["key_hint"] == "…cret"

    empty = client.post(
        f"/app/providers/{connection['id']}/credential",
        data={"api_key": "   "},
        headers={"X-CSRF-Token": csrf},
    )
    assert empty.status_code == 422

    other_workspace = fake_pb.seed(
        "workspaces", {"name": "Other", "slug": "other", "owner": "u2"}
    )
    foreign = _seed_connection(fake_pb, other_workspace["id"], name="Foreign")
    denied = client.post(
        f"/app/providers/{foreign['id']}/credential",
        data={"api_key": "sk-foreign"},
        headers={"X-CSRF-Token": csrf},
    )
    assert denied.status_code == 404
    assert all(
        credential["connection"] != foreign["id"]
        for credential in fake_pb.collections.get("provider_credentials", {}).values()
    )
