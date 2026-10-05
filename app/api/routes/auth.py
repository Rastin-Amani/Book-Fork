"""Authentication routes (browser-facing, HTMX-friendly).

The API layer only orchestrates: it validates input, delegates to the auth
provider, and sets/clears the session cookie. Business logic lives in
``app.auth``.
"""

from __future__ import annotations

import contextlib
from typing import Annotated

from fastapi import APIRouter, Form, Request, Response
from pydantic import EmailStr

from app.api.dependencies import (
    AuthRateLimited,
    CsrfProtected,
    CtxDep,
    CurrentUser,
    PasswordResetRateLimited,
    SignupRateLimited,
)
from app.exceptions import AuthenticationError, ConflictError, NotFoundError, ValidationError
from app.logging import get_logger
from app.observability.events import (
    LOGIN,
    PASSWORD_RESET_REQUESTED,
    SIGNUP,
    emit,
)
from app.schemas.auth import UserOut
from app.web.templating import render

logger = get_logger(__name__)

router = APIRouter(tags=["auth"])

MIN_PASSWORD_LENGTH = 8


def _redirect(response: Response, location: str) -> Response:
    response.headers["HX-Redirect"] = location
    return response


def _error(request: Request, message: str, status_code: int) -> Response:
    return render(
        request, "partials/auth_error.html", {"message": message}, status_code=status_code
    )


@router.post("/auth/login")
async def login(
    request: Request,
    ctx: CtxDep,
    _csrf: CsrfProtected,
    _rl: AuthRateLimited,
    identity: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> Response:
    try:
        session = await ctx.auth.login(identity=identity, password=password)
    except AuthenticationError:
        return _error(request, "Invalid email or password.", 401)
    except ValidationError:
        return _error(request, "Invalid email or password.", 401)

    response = Response(status_code=200)
    ctx.sessions.set_cookie(response, session.token)
    emit(LOGIN, user_id=session.user.id)
    return _redirect(response, "/app")


@router.post("/auth/signup")
async def signup(
    request: Request,
    ctx: CtxDep,
    _csrf: CsrfProtected,
    _rl: AuthRateLimited,
    _signup_rl: SignupRateLimited,
    email: Annotated[EmailStr, Form()],
    password: Annotated[str, Form()],
    name: Annotated[str, Form()] = "",
) -> Response:
    if len(password) < MIN_PASSWORD_LENGTH:
        return _error(request, f"Password must be at least {MIN_PASSWORD_LENGTH} characters.", 422)
    try:
        session = await ctx.auth.signup(
            email=str(email), password=password, name=name.strip() or None
        )
    except ConflictError:
        return _error(request, "An account with that email already exists.", 409)
    except ValidationError:
        return _error(request, "Could not create the account. Check your details.", 422)

    response = Response(status_code=200)
    ctx.sessions.set_cookie(response, session.token)
    emit(SIGNUP, user_id=session.user.id)
    return _redirect(response, "/app")


@router.post("/auth/logout")
async def logout(request: Request, ctx: CtxDep, _csrf: CsrfProtected) -> Response:
    token = getattr(request.state, "auth_token", None)
    if token:
        await ctx.auth.logout(token=token)
    response = Response(status_code=200)
    ctx.sessions.clear_cookie(response)
    return _redirect(response, "/login")


@router.post("/auth/password-reset")
async def request_password_reset(
    request: Request,
    ctx: CtxDep,
    _csrf: CsrfProtected,
    _rl: AuthRateLimited,
    _reset_rl: PasswordResetRateLimited,
    email: Annotated[EmailStr, Form()],
) -> Response:
    # Never reveal whether an account exists.
    with contextlib.suppress(ValidationError, NotFoundError):
        await ctx.auth.request_password_reset(email=str(email))
    emit(PASSWORD_RESET_REQUESTED)
    return render(
        request,
        "partials/auth_success.html",
        {"message": "If that email exists, a reset link has been sent."},
    )


@router.post("/auth/password-reset/confirm")
async def confirm_password_reset(
    request: Request,
    ctx: CtxDep,
    _csrf: CsrfProtected,
    token: Annotated[str, Form()],
    password: Annotated[str, Form()],
    password_confirm: Annotated[str, Form()],
) -> Response:
    if password != password_confirm:
        return _error(request, "Passwords do not match.", 422)
    if len(password) < MIN_PASSWORD_LENGTH:
        return _error(request, f"Password must be at least {MIN_PASSWORD_LENGTH} characters.", 422)
    try:
        await ctx.auth.confirm_password_reset(
            token=token, password=password, password_confirm=password_confirm
        )
    except ValidationError:
        return _error(request, "This reset link is invalid or has expired.", 422)

    response = Response(status_code=200)
    return _redirect(response, "/login")


@router.post("/auth/verify-email")
async def request_verification(
    request: Request,
    ctx: CtxDep,
    _csrf: CsrfProtected,
    _rl: AuthRateLimited,
    email: Annotated[EmailStr, Form()],
) -> Response:
    with contextlib.suppress(ValidationError, NotFoundError):
        await ctx.auth.request_verification(email=str(email))
    return render(
        request,
        "partials/auth_success.html",
        {"message": "If that email exists, a verification link has been sent."},
    )


@router.post("/auth/verify-email/confirm")
async def confirm_verification(
    request: Request,
    ctx: CtxDep,
    _csrf: CsrfProtected,
    token: Annotated[str, Form()],
) -> Response:
    try:
        await ctx.auth.confirm_verification(token=token)
    except ValidationError:
        return _error(request, "This verification link is invalid or has expired.", 422)
    return render(request, "partials/auth_success.html", {"message": "Your email is verified."})


@router.get("/api/me", response_model=UserOut)
async def current_user(user: CurrentUser) -> UserOut:
    """Current-user endpoint for programmatic clients."""
    return UserOut(id=user.id, email=user.email, name=user.name, verified=user.verified)
