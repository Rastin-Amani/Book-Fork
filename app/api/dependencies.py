"""FastAPI dependencies: cross-cutting concerns wired once and shared.

Routes use these instead of copy-pasting auth, CSRF, rate limiting, or context
lookups. Authorization is enforced here, never by hiding UI.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, cast

from fastapi import Depends, Request

from app.api.repositories import Repositories, build_repositories
from app.auth.base import AuthUser
from app.context import AppContext
from app.exceptions import (
    AuthenticationError,
    ConfigurationError,
    PermissionDeniedError,
    UpstreamError,
)
from app.schemas.workspaces import Workspace
from app.security.csrf import CSRF_COOKIE_NAME, CSRF_FORM_FIELD, CSRF_HEADER_NAME
from app.workspaces.service import WorkspaceService


def get_ctx(request: Request) -> AppContext:
    """Return the application context from ``app.state``."""
    return cast(AppContext, request.app.state.ctx)


CtxDep = Annotated[AppContext, Depends(get_ctx)]


def get_client_ip(request: Request) -> str:
    """Best-effort client identity for rate limiting.

    ``request.client`` is the peer address. We deliberately do not trust
    ``X-Forwarded-For`` unless a trusted proxy layer is configured.
    """
    return request.client.host if request.client else "unknown"


async def get_optional_user(request: Request) -> AuthUser | None:
    """Return the authenticated user if any, else ``None``."""
    return cast(AuthUser | None, getattr(request.state, "user", None))


async def get_current_user(request: Request) -> AuthUser:
    """Require an authenticated user or raise 401/503."""
    user = getattr(request.state, "user", None)
    if user is None and getattr(request.state, "upstream_error", False):
        raise UpstreamError("The identity service is unavailable.")
    if user is None:
        raise AuthenticationError()
    return cast(AuthUser, user)


async def require_csrf(request: Request) -> None:
    """Validate the CSRF token for state-changing requests."""
    ctx = get_ctx(request)
    token = request.headers.get(CSRF_HEADER_NAME)
    if not token:
        try:
            form = await request.form()
            value = form.get(CSRF_FORM_FIELD)
            token = value if isinstance(value, str) else None
        except Exception:
            token = None
    cookie = request.cookies.get(CSRF_COOKIE_NAME)
    if not ctx.csrf.is_valid(token, cookie):
        raise PermissionDeniedError("Invalid or missing CSRF token.")


async def enforce_auth_rate_limit(request: Request) -> None:
    """Rate limit authentication endpoints per client."""
    ctx = get_ctx(request)
    if ctx.settings.rate_limit_enabled:
        ctx.auth_limiter.check(get_client_ip(request))


CurrentUser = Annotated[AuthUser, Depends(get_current_user)]
OptionalUser = Annotated[AuthUser | None, Depends(get_optional_user)]
CsrfProtected = Annotated[None, Depends(require_csrf)]
AuthRateLimited = Annotated[None, Depends(enforce_auth_rate_limit)]


async def get_repositories(request: Request) -> Repositories:
    """Repositories bound to the requesting user's PocketBase token."""
    ctx = get_ctx(request)
    token = cast("str | None", getattr(request.state, "auth_token", None))
    return build_repositories(ctx.pocketbase, token=token)


ReposDep = Annotated[Repositories, Depends(get_repositories)]


def get_user_token(request: Request) -> str | None:
    return cast("str | None", getattr(request.state, "auth_token", None))


UtilityToken = Annotated[str | None, Depends(get_user_token)]


async def get_workspace(request: Request, user: CurrentUser, repos: ReposDep) -> Workspace:
    """Resolve (creating on first use) the user's personal workspace.

    Memoized per user for a short window: the personal workspace is a stable
    1:1 mapping and every authenticated page depends on it, so re-reading it on
    each request is pure repeated work.
    """
    ctx = get_ctx(request)
    cached = ctx.workspace_cache.get(user.id)
    if cached is not None:
        return cached
    service = WorkspaceService(
        repos.workspaces, repos.workspace_members, token=get_user_token(request)
    )
    workspace = await service.get_or_create_personal(user.id)
    ctx.workspace_cache.set(user.id, workspace)
    return workspace


WorkspaceDep = Annotated[Workspace, Depends(get_workspace)]


def get_workspace_service(request: Request, repos: ReposDep) -> WorkspaceService:
    return WorkspaceService(
        repos.workspaces, repos.workspace_members, token=get_user_token(request)
    )


WorkspaceServiceDep = Annotated[WorkspaceService, Depends(get_workspace_service)]


async def require_admin(user: CurrentUser, repos: ReposDep) -> AuthUser:
    """Administrator gate based on the configured ``admin.emails`` setting."""
    setting = await repos.settings.get_by_key("admin.emails")
    emails = setting.value if setting is not None else []
    if not isinstance(emails, list) or (user.email or "") not in emails:
        raise PermissionDeniedError("Administrator access required.")
    return user


AdminUser = Annotated[AuthUser, Depends(require_admin)]


def rate_limit(bucket: str) -> Callable[[Request, AuthUser | None], Awaitable[None]]:
    """Build a dependency that rate limits ``bucket`` per user (or client IP)."""

    async def _dependency(request: Request, user: OptionalUser = None) -> None:
        ctx = get_ctx(request)
        if not ctx.settings.rate_limit_enabled:
            return
        limiter = ctx.limiters.get(bucket)
        if limiter is None:
            return
        identity = user.id if user is not None else get_client_ip(request)
        limiter.check(f"{bucket}:{identity}")

    return _dependency


UploadRateLimited = Annotated[None, Depends(rate_limit("upload"))]
TranslationRateLimited = Annotated[None, Depends(rate_limit("translation"))]
RetryRateLimited = Annotated[None, Depends(rate_limit("retry"))]
ProviderTestRateLimited = Annotated[None, Depends(rate_limit("provider_test"))]
SignupRateLimited = Annotated[None, Depends(rate_limit("signup"))]
PasswordResetRateLimited = Annotated[None, Depends(rate_limit("password_reset"))]


async def get_admin_repositories(ctx: CtxDep) -> Repositories:
    """Repositories bound to the superuser service token for admin operations.

    Admin pages intentionally bypass per-user rules to inspect every workspace;
    the caller is already gated by :func:`require_admin`.
    """
    token = await ctx.ensure_service_token()
    if token is None:
        raise ConfigurationError(
            "Admin pages require POCKETBASE_SERVICE_CREDENTIAL to be configured."
        )
    return build_repositories(ctx.pocketbase, token=token)


AdminReposDep = Annotated[Repositories, Depends(get_admin_repositories)]
