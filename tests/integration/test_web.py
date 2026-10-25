"""Integration tests for health, pages, auth, and CSRF — no live PocketBase."""

from __future__ import annotations

from typing import Any, ClassVar

from app.auth.base import AuthSession, AuthUser, OAuthProvider
from app.exceptions import AuthenticationError, UpstreamError
from app.services.health import CheckResult, ReadinessReport
from fastapi.testclient import TestClient


class FakeAuthProvider:
    """In-memory OAuth provider implementing the AuthProvider protocol."""

    PROVIDERS: ClassVar[list[OAuthProvider]] = [
        OAuthProvider(
            name="google",
            auth_url=(
                "https://accounts.google.com/o/oauth2/v2/auth"
                "?client_id=g&state=st-google&redirect_uri="
            ),
            state="st-google",
            verifier="verifier-google",
        ),
        OAuthProvider(
            name="github",
            auth_url=(
                "https://github.com/login/oauth/authorize?client_id=h&state=st-github&redirect_uri="
            ),
            state="st-github",
            verifier="verifier-github",
        ),
    ]

    def __init__(
        self,
        *,
        unavailable: bool = False,
        fail_exchange: bool = False,
        providers: list[OAuthProvider] | None = None,
    ) -> None:
        self.unavailable = unavailable
        self.fail_exchange = fail_exchange
        self.providers = list(self.PROVIDERS if providers is None else providers)
        self.logged_out: list[str] = []

    async def oauth_providers(self) -> list[OAuthProvider]:
        if self.unavailable:
            raise UpstreamError("identity service down")
        return list(self.providers)

    async def login_with_oauth2(
        self, *, provider: str, code: str, code_verifier: str, redirect_url: str
    ) -> AuthSession:
        if self.unavailable:
            raise UpstreamError("identity service down")
        if self.fail_exchange or code != "good-code":
            raise AuthenticationError()
        return AuthSession(token="pb-token", user=self._user())

    async def refresh(self, *, token: str) -> AuthSession:
        if token != "pb-token":
            raise AuthenticationError()
        return AuthSession(token=token, user=self._user())

    async def logout(self, *, token: str) -> None:
        self.logged_out.append(token)

    @staticmethod
    def _user() -> AuthUser:
        return AuthUser(id="u1", email="a@b.co", name="Test", verified=True)


class StubHealthService:
    def __init__(self, ready: bool) -> None:
        self._ready = ready

    async def readiness(self) -> ReadinessReport:
        return ReadinessReport(ready=self._ready, checks=[CheckResult("pocketbase", self._ready)])


def _sign_in(client: TestClient) -> None:
    client.get("/login")
    response = client.get(
        "/auth/oauth2/callback?code=good-code&state=st-google", follow_redirects=False
    )
    assert response.status_code == 303


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


def test_web_shell_shows_release_version(client: TestClient) -> None:
    from app.version import __version__

    response = client.get("/login")
    assert f"Book Fork v{__version__}" in response.text


def test_api_me_requires_auth(client: TestClient) -> None:
    response = client.get("/api/me")
    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"


def test_dashboard_redirects_anonymous(client: TestClient) -> None:
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_mutation_without_csrf_is_forbidden(client: TestClient) -> None:
    response = client.post("/auth/logout")
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


def test_login_page_offers_only_google_and_github(client: TestClient, app: Any) -> None:
    app.state.ctx.auth = FakeAuthProvider()
    response = client.get("/login")

    assert response.status_code == 200
    assert "Continue with Google" in response.text
    assert "Continue with GitHub" in response.text
    assert "Sign in or create an account" in response.text
    # No password UI survives.
    assert 'type="password"' not in response.text
    assert "<form" not in response.text
    # Provider URLs point at our callback, never PocketBase's dashboard.
    assert "redirect_uri=http%3A%2F%2Ftestserver%2Fauth%2Foauth2%2Fcallback" in response.text
    assert "no-store" in response.headers.get("cache-control", "")

    cookies = " ".join(response.headers.get_list("set-cookie"))
    assert "oauth_state=" in cookies and "HttpOnly" in cookies and "Path=/auth" in cookies


def test_signup_redirects_to_the_single_login_page(client: TestClient) -> None:
    response = client.get("/signup", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_login_page_hides_unconfigured_providers(client: TestClient, app: Any) -> None:
    app.state.ctx.auth = FakeAuthProvider(providers=FakeAuthProvider.PROVIDERS[:1])

    response = client.get("/login")
    assert "Continue with Google" in response.text
    assert "Continue with GitHub" not in response.text


def test_login_page_without_providers_explains_the_problem(client: TestClient, app: Any) -> None:
    app.state.ctx.auth = FakeAuthProvider(providers=[])

    response = client.get("/login")
    assert response.status_code == 200
    assert "Sign-in is not configured yet" in response.text
    assert "oauth_state=" not in " ".join(response.headers.get_list("set-cookie"))


def test_login_page_survives_identity_outage(client: TestClient, app: Any) -> None:
    app.state.ctx.auth = FakeAuthProvider(unavailable=True)
    response = client.get("/login")
    assert response.status_code == 200
    assert "Sign-in is temporarily unavailable" in response.text
    assert "Try again" in response.text


def test_password_login_post_is_gone(client: TestClient, app: Any) -> None:
    app.state.ctx.auth = FakeAuthProvider()
    response = client.post(
        "/login",
        data={"identity": "a@b.co", "password": "secret"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/login?error=password"
    assert "book_fork_session" not in client.cookies
    assert client.get("/app").status_code == 401


def test_oauth_callback_sets_session_and_redirects(client: TestClient, app: Any) -> None:
    app.state.ctx.auth = FakeAuthProvider()
    client.get("/login")

    response = client.get(
        "/auth/oauth2/callback?code=good-code&state=st-google", follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/app"
    assert client.cookies.get("book_fork_session")

    cookies = " ".join(response.headers.get_list("set-cookie"))
    assert "oauth_state=" in cookies and "Max-Age=0" in cookies


def test_oauth_callback_works_for_github(client: TestClient, app: Any) -> None:
    app.state.ctx.auth = FakeAuthProvider()
    client.get("/login")
    response = client.get(
        "/auth/oauth2/callback?code=good-code&state=st-github", follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/app"


def test_oauth_callback_rejects_a_forged_state(client: TestClient, app: Any) -> None:
    app.state.ctx.auth = FakeAuthProvider()
    client.get("/login")

    response = client.get(
        "/auth/oauth2/callback?code=good-code&state=not-from-the-cookie",
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/login?error=state"
    assert "book_fork_session" not in client.cookies


def test_oauth_callback_without_state_cookie_rejected(client: TestClient, app: Any) -> None:
    app.state.ctx.auth = FakeAuthProvider()
    response = client.get(
        "/auth/oauth2/callback?code=good-code&state=st-google", follow_redirects=False
    )
    assert response.headers["location"] == "/login?error=state"


def test_oauth_callback_rejects_non_ascii_state(client: TestClient, app: Any) -> None:
    app.state.ctx.auth = FakeAuthProvider()
    client.get("/login")
    response = client.get(
        "/auth/oauth2/callback?code=good-code&state=%C3%A9", follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/login?error=state"


def test_oauth_callback_cancelled(client: TestClient, app: Any) -> None:
    app.state.ctx.auth = FakeAuthProvider()
    response = client.get(
        "/auth/oauth2/callback?error=access_denied&state=st-google", follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/login?error=cancelled"


def test_oauth_callback_rejected_code(client: TestClient, app: Any) -> None:
    app.state.ctx.auth = FakeAuthProvider()
    client.get("/login")
    response = client.get(
        "/auth/oauth2/callback?code=bad-code&state=st-google", follow_redirects=False
    )
    assert response.headers["location"] == "/login?error=failed"
    assert "book_fork_session" not in client.cookies


def test_oauth_callback_survives_identity_outage(client: TestClient, app: Any) -> None:
    provider = FakeAuthProvider()
    app.state.ctx.auth = provider
    client.get("/login")
    # The page loaded while PocketBase was reachable; the exchange then fails.
    provider.unavailable = True
    response = client.get(
        "/auth/oauth2/callback?code=good-code&state=st-google", follow_redirects=False
    )
    assert response.headers["location"] == "/login?error=unavailable"


def test_oauth_error_is_shown_on_the_login_page(client: TestClient, app: Any) -> None:
    app.state.ctx.auth = FakeAuthProvider()
    response = client.get("/login?error=state")
    assert response.status_code == 200
    assert 'role="status"' in response.text
    assert "sign-in link expired" in response.text


def test_authenticated_dashboard_redirects_to_app(client: TestClient, app: Any) -> None:
    app.state.ctx.auth = FakeAuthProvider()
    _sign_in(client)

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
    _sign_in(client)
    csrf = client.cookies.get("book_fork_csrf")

    response = client.post("/auth/logout", headers={"X-CSRF-Token": csrf or ""})
    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == "/login"
    assert not client.cookies.get("book_fork_session")
    assert provider.logged_out == ["pb-token"]
