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
