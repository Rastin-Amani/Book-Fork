"""FastAPI application entrypoint.

Run locally with::

    uv run fastapi dev app/main.py
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES, GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response

from app.api.routes import (
    admin,
    auth,
    glossaries,
    health,
    pages,
    providers,
    settings_pages,
    translate,
)
from app.api.routes import app as app_routes
from app.config import Settings, get_settings
from app.context import build_context, close_context
from app.exceptions import BookForkError
from app.logging import configure_logging, get_logger
from app.version import __version__
from app.web.middleware import RequestContextMiddleware
from app.web.security_headers import SecurityHeadersMiddleware
from app.web.templating import render

logger = get_logger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    configure_logging(level=settings.log_level, json_logs=settings.log_json)
    logger.info("startup", app_env=settings.app_env, storage=settings.storage_backend)
    context = await build_context(settings)
    app.state.ctx = context
    try:
        yield
    finally:
        await close_context(context)
        logger.info("shutdown")


def _wants_html(request: Request) -> bool:
    if request.url.path.startswith("/api/"):
        return False
    return "text/html" in request.headers.get("accept", "")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = settings or get_settings()
    docs_enabled = settings.enable_docs and not settings.is_production

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
        root_path=settings.root_path,
    )
    app.state.settings = settings

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
    app.add_middleware(
        GZipMiddleware,
        minimum_size=500,
        # Compress HTML/JSON/CSS/JS, but never already-compressed documents.
        exclude_content_types=(
            *DEFAULT_EXCLUDED_CONTENT_TYPES,
            "application/pdf",
            "application/epub+zip",
            "application/octet-stream",
        ),
    )
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )
    if settings.security_headers_enabled:
        app.add_middleware(
            SecurityHeadersMiddleware,
            csp=settings.content_security_policy,
            hsts=settings.is_production,
        )

    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(pages.router)
    app.include_router(app_routes.router)
    app.include_router(translate.router)
    app.include_router(providers.router)
    app.include_router(glossaries.router)
    app.include_router(settings_pages.router)
    app.include_router(admin.router)

    _register_exception_handlers(app)
    return app


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(BookForkError)
    async def _book_fork_error(request: Request, exc: BookForkError) -> Response:
        if _wants_html(request):
            return render(
                request,
                "pages/error.html",
                {"status_code": exc.status_code, "message": exc.message},
                status_code=exc.status_code,
            )
        return JSONResponse({"code": exc.code, "message": exc.message}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> Response:
        if _wants_html(request):
            return render(
                request,
                "pages/error.html",
                {"status_code": 422, "message": "The submitted data is invalid."},
                status_code=422,
            )
        return JSONResponse(
            {"code": "validation_error", "message": "The submitted data is invalid."},
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> Response:
        if _wants_html(request):
            return render(
                request,
                "pages/error.html",
                {"status_code": exc.status_code, "message": str(exc.detail)},
                status_code=exc.status_code,
            )
        return JSONResponse(
            {"code": "http_error", "message": str(exc.detail)}, status_code=exc.status_code
        )

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> Response:
        logger.exception("unhandled_exception", path=request.url.path, error=type(exc).__name__)
        if _wants_html(request):
            return render(
                request,
                "pages/error.html",
                {"status_code": 500, "message": "An unexpected error occurred."},
                status_code=500,
            )
        return JSONResponse(
            {"code": "internal_error", "message": "An unexpected error occurred."}, status_code=500
        )


app = create_app()
