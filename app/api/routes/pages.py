"""Server-rendered pages (full document or HTMX content region)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from app.api.dependencies import OptionalUser
from app.web.templating import render

router = APIRouter(tags=["pages"])


@router.get("/")
@router.get("/dashboard")
async def home(request: Request, user: OptionalUser = None) -> Response:
    """The app root: straight to the workspace, or to login when anonymous."""
    if user is None:
        return RedirectResponse("/login", status_code=303)
    return RedirectResponse("/app", status_code=303)


@router.get("/login")
async def login_page(request: Request, user: OptionalUser = None) -> Response:
    if user is not None:
        return RedirectResponse("/app", status_code=303)
    return render(request, "pages/login.html", {})


@router.get("/signup")
async def signup_page(request: Request, user: OptionalUser = None) -> Response:
    if user is not None:
        return RedirectResponse("/app", status_code=303)
    return render(request, "pages/signup.html", {})


@router.get("/forgot-password")
async def forgot_password_page(request: Request) -> Response:
    return render(request, "pages/forgot_password.html", {})


@router.get("/reset-password")
async def reset_password_page(request: Request, token: str = "") -> Response:
    return render(request, "pages/reset_password.html", {"token": token})


@router.get("/verify-email")
async def verify_email_page(request: Request, token: str = "") -> Response:
    return render(request, "pages/verify_email.html", {"token": token})
