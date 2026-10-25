"""Server-rendered pages (full document or HTMX content region)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from app.api.dependencies import OptionalUser

router = APIRouter(tags=["pages"])


@router.get("/")
@router.get("/dashboard")
async def home(request: Request, user: OptionalUser = None) -> Response:
    """The app root: straight to the workspace, or to login when anonymous."""
    if user is None:
        return RedirectResponse("/login", status_code=303)
    return RedirectResponse("/app", status_code=303)
