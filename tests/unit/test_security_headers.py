"""Browser security response headers."""

from __future__ import annotations

from app.web.security_headers import DEFAULT_CSP
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_security_headers_present_on_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["Content-Security-Policy"] == DEFAULT_CSP
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "Permissions-Policy" in response.headers


def test_csp_remains_htmx_alpine_compatible() -> None:
    # Alpine's standard build evaluates expressions with new Function and both
    # Alpine and daisyUI set inline styles; the default policy must allow them.
    assert "'unsafe-eval'" in DEFAULT_CSP
    assert "'unsafe-inline'" in DEFAULT_CSP
    assert "frame-ancestors 'none'" in DEFAULT_CSP


def test_headers_can_be_disabled(settings) -> None:
    from app.main import create_app

    disabled = settings.model_copy(update={"security_headers_enabled": False})
    app: FastAPI = create_app(disabled)
    with TestClient(app) as client:
        response = client.get("/health")
    assert "Content-Security-Policy" not in response.headers
