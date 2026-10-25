"""Integration tests for health, pages, auth, and CSRF — no live PocketBase."""

from __future__ import annotations

from typing import Any

from app.auth.base import AuthSession, AuthUser
from app.exceptions import AuthenticationError
from app.services.health import CheckResult, ReadinessReport
from fastapi.testclient import TestClient


class FakeAuthProvider:
    """In-memory auth provider implementing the AuthProvider protocol."""

    def __init__(self, *, fail_login: bool = False) -> None:
        self.fail_login = fail_login
        self.logged_out: list[str] = []

    async def login(self, *, identity: str, password: str) -> AuthSession:
        if self.fail_login:
            raise AuthenticationError()
        return AuthSession(token="pb-token", user=self._user(identity))

    async def signup(self, *, email: str, password: str, name: str | None = None) -> AuthSession:
        return AuthSession(token="pb-token", user=self._user(email, name))

    async def refresh(self, *, token: str) -> AuthSession:
        if token != "pb-token":
            raise AuthenticationError()
        return AuthSession(token=token, user=self._user("a@b.co", "Test"))

    async def logout(self, *, token: str) -> None:
        self.logged_out.append(token)

    async def request_password_reset(self, *, email: str) -> None:
        return None

    async def confirm_password_reset(
        self, *, token: str, password: str, password_confirm: str
    ) -> None:
        return None

    async def request_verification(self, *, email: str) -> None:
        return None

    async def confirm_verification(self, *, token: str) -> None:
        return None

    @staticmethod
    def _user(email: str, name: str | None = "Test") -> AuthUser:
        return AuthUser(id="u1", email=email, name=name, verified=True)


class StubHealthService:
    def __init__(self, ready: bool) -> None:
        self._ready = ready

    async def readiness(self) -> ReadinessReport:
        return ReadinessReport(ready=self._ready, checks=[CheckResult("pocketbase", self._ready)])


def test_health_liveness(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_index_redirects_anonymous_to_login(client: TestClient) -> None:
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_login_page_sets_csrf_cookie(client: TestClient) -> None:
    response = client.get("/login")
    assert response.status_code == 200
    assert "book_fork_csrf" in response.cookies


def test_api_me_requires_auth(client: TestClient) -> None:
    response = client.get("/api/me")
    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"


def test_dashboard_redirects_anonymous(client: TestClient) -> None:
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_mutation_without_csrf_is_forbidden(client: TestClient) -> None:
    response = client.post("/auth/login", data={"identity": "a@b.co", "password": "secret123"})
    assert response.status_code == 403


def test_readiness_ok(client: TestClient, app: Any) -> None:
    app.state.ctx.health = StubHealthService(ready=True)
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["ready"] is True


def test_readiness_degraded(client: TestClient, app: Any) -> None:
    app.state.ctx.health = StubHealthService(ready=False)
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["ready"] is False


def test_login_flow_sets_session_and_redirects(client: TestClient, app: Any) -> None:
    app.state.ctx.auth = FakeAuthProvider()
    client.get("/login")
    csrf = client.cookies.get("book_fork_csrf")
    assert csrf

    response = client.post(
        "/auth/login",
        data={"identity": "a@b.co", "password": "secret123"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == "/app"
    assert client.cookies.get("book_fork_session")


def test_failed_login_returns_401_fragment(client: TestClient, app: Any) -> None:
    app.state.ctx.auth = FakeAuthProvider(fail_login=True)
    client.get("/login")
    csrf = client.cookies.get("book_fork_csrf")

    response = client.post(
        "/auth/login",
        data={"identity": "a@b.co", "password": "wrong"},
        headers={"X-CSRF-Token": csrf, "Accept": "text/html"},
    )
    assert response.status_code == 401
    assert 'role="alert"' in response.text
    assert "Invalid email or password." in response.text


def test_authenticated_dashboard_redirects_to_app(client: TestClient, app: Any) -> None:
    app.state.ctx.auth = FakeAuthProvider()
    client.get("/login")
    csrf = client.cookies.get("book_fork_csrf")
    client.post(
        "/auth/login",
        data={"identity": "a@b.co", "password": "secret123"},
        headers={"X-CSRF-Token": csrf},
    )

    full = client.get("/dashboard", follow_redirects=False)
    assert full.status_code == 303
    assert full.headers["location"] == "/app"

    root = client.get("/", follow_redirects=False)
    assert root.status_code == 303
    assert root.headers["location"] == "/app"


def test_partial_rendering_for_htmx(client: TestClient) -> None:
    full = client.get("/login")
    assert full.status_code == 200
    assert "<!doctype html>" in full.text.lower()

    partial = client.get("/login", headers={"HX-Request": "true"})
    assert partial.status_code == 200
    assert "<!doctype html>" not in partial.text.lower()
    assert '<main id="app-content"' in partial.text


def test_protected_app_routes_require_auth(client: TestClient) -> None:
    assert client.get("/app").status_code == 401
    assert client.get("/app/translations").status_code == 401
    assert client.get("/app/providers").status_code == 401
    assert client.get("/admin").status_code == 401


def test_logout_clears_session(client: TestClient, app: Any) -> None:
    provider = FakeAuthProvider()
    app.state.ctx.auth = provider
    client.get("/login")
    csrf = client.cookies.get("book_fork_csrf")
    client.post(
        "/auth/login",
        data={"identity": "a@b.co", "password": "secret123"},
        headers={"X-CSRF-Token": csrf},
    )
    assert client.cookies.get("book_fork_session")

    response = client.post("/auth/logout", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == "/login"
    assert not client.cookies.get("book_fork_session")
