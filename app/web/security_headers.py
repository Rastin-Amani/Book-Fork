"""Browser security response headers.

A single place that attaches defensive headers to every response. The CSP is
compatible with the actual HTMX + Alpine + daisyUI setup: Alpine's standard build
evaluates expressions with ``new Function`` (hence ``'unsafe-eval'``) and daisyUI
plus Alpine set inline style attributes (hence ``style-src 'unsafe-inline'``).
Blindly shipping a maximally strict CSP would break the application, so the
policy is explicit and documented rather than copied.

The policy is overridable with ``CONTENT_SECURITY_POLICY`` for deployments that
build Alpine's CSP-compatible bundle or otherwise tighten it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

DEFAULT_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "object-src 'none'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object, *, csp: str | None = None, hsts: bool = False) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._csp = csp or DEFAULT_CSP
        self._hsts = hsts

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        headers = response.headers
        headers.setdefault("Content-Security-Policy", self._csp)
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()"
        )
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if self._hsts:
            headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response
