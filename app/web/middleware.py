"""Request-scoped browser context middleware.

Responsibilities (one pass per request):

* ensure a CSRF cookie/token exists and expose it on ``request.state``;
* resolve the encrypted session cookie into a validated user via the auth
  provider, rotating/clearing the cookie as needed.

This keeps cookie handling and identity resolution out of every route.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.context import AppContext
from app.exceptions import AuthenticationError, UpstreamError
from app.logging import get_logger
from app.observability.context import clear as clear_observability_context
from app.observability.context import new_request_id, set_request_id
from app.security.csrf import CSRF_COOKIE_NAME, CSRF_MAX_AGE_SECONDS

logger = get_logger(__name__)

# Paths that must not trigger an upstream auth refresh (cheap or asset traffic).
_SKIP_PREFIXES = ("/static", "/health", "/favicon", "/docs", "/redoc", "/openapi.json")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Populates request state with CSRF token and resolved user."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        ctx: AppContext = request.app.state.ctx
        request_id = set_request_id(new_request_id())
        self._init_state(request)
        new_csrf = self._prepare_csrf(request, ctx)

        rotated_token: str | None = None
        clear_session = False

        if not request.url.path.startswith(_SKIP_PREFIXES):
            raw = request.cookies.get(ctx.sessions.cookie_name)
            token = ctx.sessions.decode(raw)
            if token:
                # Reuse a recently validated session instead of hitting the
                # identity service on every request. A miss (or an entry past
                # its short TTL) revalidates as before; the cache only removes
                # duplicate work within the window.
                session = ctx.session_cache.get(token)
                if session is None:
                    try:
                        session = await ctx.auth.refresh(token=token)
                    except AuthenticationError:
                        clear_session = True
                    except UpstreamError:
                        # Be truthful: an auth dependency can surface this as 503.
                        request.state.upstream_error = True
                    else:
                        ctx.session_cache.set(session.token, session)
                if session is not None:
                    request.state.user = session.user
                    request.state.auth_token = session.token
                    if session.token != token:
                        rotated_token = session.token

        response = await call_next(request)

        response.headers.setdefault("X-Request-ID", request_id)

        if new_csrf:
            response.set_cookie(
                key=CSRF_COOKIE_NAME,
                value=request.state.csrf_token,
                max_age=CSRF_MAX_AGE_SECONDS,
                httponly=True,
                secure=bool(ctx.settings.cookie_secure),
                samesite=ctx.settings.cookie_samesite,
                domain=ctx.settings.cookie_domain,
                path="/",
            )
        if rotated_token:
            ctx.sessions.set_cookie(response, rotated_token)
        if clear_session:
            ctx.sessions.clear_cookie(response)
        clear_observability_context()
        return response

    @staticmethod
    def _init_state(request: Request) -> None:
        request.state.user = None
        request.state.auth_token = None
        request.state.upstream_error = False
        request.state.csrf_token = ""

    @staticmethod
    def _prepare_csrf(request: Request, ctx: AppContext) -> bool:
        cookie_value = request.cookies.get(CSRF_COOKIE_NAME)
        if cookie_value:
            request.state.csrf_token = cookie_value
            return False
        request.state.csrf_token = ctx.csrf.issue()
        return True
