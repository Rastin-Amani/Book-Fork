"""Authentication — PocketBase OAuth2 (Google / GitHub) and the session cookie.

There is no password sign-in: PocketBase's users collection only allows the
Google and GitHub OAuth2 providers. Sign-in and sign-up are the same action
(the provider creates the account on first use and links an existing record by
verified email), so there is a single page; ``/signup`` redirects to it.

Flow (PocketBase "manual code exchange"):
1. ``GET /login`` asks PocketBase for the enabled providers
   (``auth-methods``). Each provider carries a one-off ``state`` + PKCE
   ``codeVerifier``; we append our callback URL to its ``authURL`` and keep the
   pair in a signed, HttpOnly, 10-minute cookie.
2. The provider redirects back to ``/auth/oauth2/callback?code=…&state=…``.
3. We match ``state`` against the cookie, exchange the code with PocketBase
   (``auth-with-oauth2``), and store the returned token in the encrypted
   session cookie the middleware already validates.

The OAuth callback is a top-level browser navigation, so failures redirect with
``?error=<code>`` (never a JSON body) and the login page renders the message.
"""

from __future__ import annotations

import hmac
import urllib.parse
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from itsdangerous import BadData, URLSafeTimedSerializer

from app.api.dependencies import (
    AuthRateLimited,
    CsrfProtected,
    CtxDep,
    CurrentUser,
    OptionalUser,
)
from app.auth.base import OAUTH_PROVIDERS, OAuthProvider
from app.config import Settings
from app.exceptions import UpstreamError
from app.logging import get_logger
from app.observability.events import LOGIN, emit
from app.schemas.auth import UserOut
from app.web.templating import render

router = APIRouter(tags=["auth"])
logger = get_logger(__name__)

OAUTH_CALLBACK_PATH = "/auth/oauth2/callback"
OAUTH_STATE_COOKIE = "oauth_state"
OAUTH_STATE_COOKIE_PATH = "/auth"
OAUTH_STATE_TTL = 10 * 60  # seconds; plenty for a provider login round trip

ERROR_MESSAGES: dict[str, tuple[str, str]] = {
    "cancelled": ("Sign-in was cancelled.", "warning"),
    "state": ("That sign-in link expired. Please try again.", "warning"),
    "unavailable": ("Could not reach the sign-in service. Please try again.", "error"),
    "failed": ("We could not complete sign-in. Please try again.", "error"),
    "password": (
        "Password sign-in is no longer available. Continue with Google or GitHub.",
        "warning",
    ),
}


# ---------------------------------------------------------------------------
# Signed state cookie
# ---------------------------------------------------------------------------
def _state_serializer(ctx: CtxDep) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(
        ctx.settings.app_secret_key.get_secret_value(), salt="oauth-state"
    )


def _read_state(ctx: CtxDep, request: Request) -> dict[str, Any]:
    """Return the verified state payload, or {} when absent/tampered/expired."""
    raw = request.cookies.get(OAUTH_STATE_COOKIE, "")
    if not raw:
        return {}
    try:
        payload = _state_serializer(ctx).loads(raw, max_age=OAUTH_STATE_TTL)
    except BadData:
        return {}
    return payload if isinstance(payload, dict) else {}


def _secure_cookie(request: Request) -> bool:
    return request.url.scheme == "https" or bool(
        getattr(request.app.state.settings, "cookie_secure", False)
    )


def oauth_callback_url(request: Request) -> str:
    """Absolute OAuth callback for this browser request.

    Built from the origin the user actually reached, not from ``APP_BASE_URL``:
    a stale canonical URL (e.g. the marketing domain) makes every provider
    reject the callback with ``redirect_uri_mismatch``. The resulting URL must
    be registered at Google/GitHub; an unregistered one is rejected by them, so
    a spoofed Host header cannot receive an auth code.
    """
    host = request.headers.get("host", "")
    settings: Settings = request.app.state.settings
    if not host:
        return settings.app_base_url.rstrip("/") + OAUTH_CALLBACK_PATH
    scheme = "https" if _secure_cookie(request) else request.url.scheme
    return f"{scheme}://{host}{OAUTH_CALLBACK_PATH}"


# ---------------------------------------------------------------------------
# Provider URLs
# ---------------------------------------------------------------------------
def provider_href(auth_url: str, callback_url: str) -> str:
    """Point the provider URL at our callback (PB leaves redirect_uri blank)."""
    parts = urllib.parse.urlsplit(auth_url)
    query = {
        key: values[0]
        for key, values in urllib.parse.parse_qs(parts.query, keep_blank_values=True).items()
    }
    query["redirect_uri"] = callback_url
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query), parts.fragment)
    )


def _provider_view(provider: OAuthProvider, callback_url: str) -> dict[str, str]:
    return {
        "name": provider.name,
        "label": OAUTH_PROVIDERS[provider.name],
        "href": provider_href(provider.auth_url, callback_url),
    }


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
def _render_auth(
    request: Request,
    ctx: CtxDep,
    *,
    error: str | None,
    providers: list[OAuthProvider],
    problem: str | None,
) -> Response:
    callback_url = oauth_callback_url(request)
    views = [_provider_view(p, callback_url) for p in providers]
    message, toast_type = ERROR_MESSAGES.get(error or "", (None, "error"))
    if not problem and not providers:
        # PocketBase answered, but neither provider is configured. This is an
        # operator problem, not a user one — say so plainly instead of showing
        # an empty login card.
        problem = "not_configured"

    response = render(
        request,
        "pages/login.html",
        {
            "title": f"Sign in · {ctx.settings.app_name}",
            "providers": views,
            "provider_text": " or ".join(p["label"] for p in views) or "Google or GitHub",
            "problem": problem,
            "error": message,
            "toast_type": toast_type,
        },
        headers={"Cache-Control": "no-store"},
    )

    if providers:
        # Merge into any still-valid state so two open tabs (or a back button)
        # do not invalidate each other's sign-in attempt.
        payload = _read_state(ctx, request)
        entries = dict(payload.get("p") or {})
        entries.update({p.name: {"s": p.state, "v": p.verifier} for p in providers})
        response.set_cookie(
            OAUTH_STATE_COOKIE,
            _state_serializer(ctx).dumps({"p": entries}),
            max_age=OAUTH_STATE_TTL,
            httponly=True,
            samesite="lax",
            secure=_secure_cookie(request),
            path=OAUTH_STATE_COOKIE_PATH,
        )
    return response


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, ctx: CtxDep, user: OptionalUser = None) -> Response:
    if user is not None:
        return RedirectResponse(url="/app", status_code=303)

    try:
        providers = await ctx.auth.oauth_providers()
        problem = None
    except Exception:
        logger.exception("auth.auth_methods_unavailable")
        providers, problem = [], "unavailable"

    return _render_auth(
        request,
        ctx,
        error=request.query_params.get("error"),
        providers=providers,
        problem=problem,
    )


@router.get("/signup")
def signup_page() -> RedirectResponse:
    """Sign-in and sign-up are one OAuth page: the provider creates the account
    on the first login and links an existing record by verified email."""
    return RedirectResponse(url="/login", status_code=303)


@router.post("/login")
def password_login_removed(request: Request) -> Response:
    """Passwords were removed. Cached/old forms land here — never 405/422."""
    target = "/login?error=password"
    if request.headers.get("HX-Request", "").lower() == "true":
        response = Response(status_code=200)
        response.headers["HX-Redirect"] = target
        return response
    return RedirectResponse(url=target, status_code=303)


# ---------------------------------------------------------------------------
# OAuth callback
# ---------------------------------------------------------------------------
@router.get(OAUTH_CALLBACK_PATH)
async def oauth_callback(request: Request, ctx: CtxDep, _rl: AuthRateLimited) -> Response:
    params = request.query_params
    if params.get("error") or not params.get("code") or not params.get("state"):
        return _fail(request, "cancelled" if params.get("error") == "access_denied" else "failed")

    state = params.get("state", "")
    entries = _read_state(ctx, request).get("p") or {}
    provider = ""
    verifier = ""
    for name, entry in entries.items():
        if isinstance(entry, dict) and hmac.compare_digest(
            str(entry.get("s") or "").encode("utf-8"), state.encode("utf-8")
        ):
            provider = str(name)
            verifier = str(entry.get("v") or "")
            break
    if provider not in OAUTH_PROVIDERS or not verifier:
        return _fail(request, "state")

    try:
        session = await ctx.auth.login_with_oauth2(
            provider=provider,
            code=params.get("code", ""),
            code_verifier=verifier,
            redirect_url=oauth_callback_url(request),
        )
    except UpstreamError:
        logger.exception("auth.oauth_unavailable", provider=provider)
        return _fail(request, "unavailable")
    except Exception:
        logger.warning("auth.oauth_rejected", provider=provider)
        return _fail(request, "failed")

    logger.info("auth.oauth_success", provider=provider)
    emit(LOGIN, user_id=session.user.id)
    # The next request already has a validated session; skip the refresh trip.
    ctx.session_cache.set(session.token, session)

    response = RedirectResponse(url="/app", status_code=303)
    response.delete_cookie(OAUTH_STATE_COOKIE, path=OAUTH_STATE_COOKIE_PATH)
    ctx.sessions.set_cookie(response, session.token)
    return response


def _fail(request: Request, error: str) -> RedirectResponse:
    """Return to the login page with a friendly code; drop the used state."""
    response = RedirectResponse(url=f"/login?error={error}", status_code=303)
    response.delete_cookie(OAUTH_STATE_COOKIE, path=OAUTH_STATE_COOKIE_PATH)
    return response


@router.post("/auth/logout")
async def logout(request: Request, ctx: CtxDep, _csrf: CsrfProtected) -> Response:
    token = getattr(request.state, "auth_token", None)
    if token:
        await ctx.auth.logout(token=token)
    response: Response = Response(status_code=200)
    response.headers["HX-Redirect"] = "/login"
    ctx.sessions.clear_cookie(response)
    response.delete_cookie(OAUTH_STATE_COOKIE, path=OAUTH_STATE_COOKIE_PATH)
    return response


@router.get("/api/me", response_model=UserOut)
async def current_user(user: CurrentUser) -> UserOut:
    """Current-user endpoint for programmatic clients."""
    return UserOut(id=user.id, email=user.email, name=user.name, verified=user.verified)
