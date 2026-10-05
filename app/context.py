"""Application context: constructed once at startup, injected via ``app.state``.

This is the composition root. It wires settings into concrete adapters (HTTP
client, PocketBase client, storage, auth provider, session/csrf managers) and
owns their lifecycle. No module-level mutable globals.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from app.auth.base import AuthSession
from app.auth.pocketbase import PocketBaseAuthProvider
from app.auth.session import SessionManager
from app.cache import TTLCache
from app.config import Settings
from app.logging import get_logger
from app.repositories.pocketbase import PocketBaseClient
from app.schemas.workspaces import Workspace
from app.security.crypto import SecretCipher
from app.security.csrf import CsrfManager
from app.security.ratelimit import RateLimiter
from app.services.health import HealthService
from app.services.service_auth import resolve_service_token
from app.storage.base import Storage
from app.storage.factory import build_storage

logger = get_logger(__name__)


@dataclass(slots=True)
class AppContext:
    """Everything a request/worker needs from the composition root."""

    settings: Settings
    http: httpx.AsyncClient
    pocketbase: PocketBaseClient
    storage: Storage
    auth: PocketBaseAuthProvider
    sessions: SessionManager
    csrf: CsrfManager
    health: HealthService
    auth_limiter: RateLimiter
    limiters: dict[str, RateLimiter]
    # Short-lived memoization of the two lookups every authenticated request
    # otherwise repeats: session validation and personal-workspace resolution.
    session_cache: TTLCache[AuthSession] = field(
        default_factory=lambda: TTLCache(ttl_seconds=30.0, maxsize=4096)
    )
    workspace_cache: TTLCache[Workspace] = field(
        default_factory=lambda: TTLCache(ttl_seconds=60.0, maxsize=4096)
    )
    _service_token: str | None = None

    async def ensure_service_token(self) -> str | None:
        """Return a cached superuser token for trusted server-side operations."""
        if self._service_token is not None:
            return self._service_token
        credential = self.settings.pocketbase_service_credential
        if credential is None:
            return None
        self._service_token = await resolve_service_token(
            self.pocketbase, credential.get_secret_value()
        )
        return self._service_token


async def build_context(settings: Settings) -> AppContext:
    """Construct the application context."""
    http = httpx.AsyncClient(base_url=settings.pocketbase_url, timeout=15.0)
    pocketbase = PocketBaseClient(settings.pocketbase_url, client=http)
    storage = build_storage(settings)

    cipher = SecretCipher.from_secret(settings.encryption_key.get_secret_value())
    sessions = SessionManager(
        cipher,
        cookie_name=settings.session_cookie_name,
        max_age_seconds=settings.session_max_age_seconds,
        secure=bool(settings.cookie_secure),
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain,
    )
    csrf = CsrfManager(settings.app_secret_key.get_secret_value())
    auth = PocketBaseAuthProvider(pocketbase, users_collection=settings.pocketbase_users_collection)
    health = HealthService(pocketbase=pocketbase, storage=storage)
    auth_limiter = RateLimiter(settings.rate_limit_auth_per_minute, window_seconds=60.0)
    limiters = {
        "signup": RateLimiter(settings.rate_limit_signup_per_minute, window_seconds=60.0),
        "password_reset": RateLimiter(
            settings.rate_limit_password_reset_per_minute, window_seconds=60.0
        ),
        "upload": RateLimiter(settings.rate_limit_upload_per_minute, window_seconds=60.0),
        "provider_test": RateLimiter(
            settings.rate_limit_provider_test_per_minute, window_seconds=60.0
        ),
        "translation": RateLimiter(settings.rate_limit_translation_per_minute, window_seconds=60.0),
        "retry": RateLimiter(settings.rate_limit_retry_per_minute, window_seconds=60.0),
    }

    return AppContext(
        settings=settings,
        http=http,
        pocketbase=pocketbase,
        storage=storage,
        auth=auth,
        sessions=sessions,
        csrf=csrf,
        health=health,
        auth_limiter=auth_limiter,
        limiters=limiters,
    )


async def close_context(context: AppContext) -> None:
    """Release resources owned by the context."""
    await context.http.aclose()
