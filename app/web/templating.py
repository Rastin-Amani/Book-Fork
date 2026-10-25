"""Jinja templating for the server-rendered web layer.

The render helper is HTMX-aware: templates receive ``is_htmx`` so the base
layout can emit only the content region for partial navigation while normal
requests get the full application shell.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates
from starlette.responses import HTMLResponse

from app.config import Settings, get_settings
from app.security.csrf import CSRF_COOKIE_NAME
from app.version import __version__

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request", "").lower() == "true"


def _context_processor(request: Request) -> dict[str, Any]:
    settings: Settings = getattr(request.app.state, "settings", None) or get_settings()
    return {
        "is_htmx": _is_htmx(request),
        "current_user": getattr(request.state, "user", None),
        "csrf_token": getattr(request.state, "csrf_token", ""),
        "csrf_cookie_name": CSRF_COOKIE_NAME,
        "app_name": settings.app_name,
        "app_version": __version__,
        "app_env": settings.app_env,
        # UI chrome locale/direction. This is presentation metadata resolved to
        # defaults for now; a locale resolver will feed it later. It is not the
        # translation source/target language.
        "html_lang": "en",
        "html_dir": "ltr",
    }


templates = Jinja2Templates(directory=str(TEMPLATES_DIR), context_processors=[_context_processor])


def _filesize(value: Any) -> str:
    """Render a byte count as a compact human string for the UI."""
    try:
        size = float(value) if value is not None else 0.0
    except TypeError, ValueError:
        return "—"
    if size <= 0:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


templates.env.filters["filesize"] = _filesize


def render(
    request: Request,
    template_name: str,
    context: dict[str, Any] | None = None,
    *,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> HTMLResponse:
    """Render a template to an HTML response."""
    response = templates.TemplateResponse(
        request=request,
        name=template_name,
        context=context or {},
        status_code=status_code,
        headers=headers,
    )
    return response
