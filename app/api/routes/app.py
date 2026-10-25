"""Authenticated application pages: dashboard, translations, documents."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse

from app.api.dependencies import CurrentUser, ReposDep, WorkspaceDep, get_ctx
from app.api.runtime import build_settings_service
from app.exceptions import NotFoundError
from app.web.templating import render

router = APIRouter(prefix="/app", tags=["app"])


@router.get("")
@router.get("/")
async def dashboard(
    request: Request, user: CurrentUser, workspace: WorkspaceDep, repos: ReposDep
) -> Response:
    jobs, documents = await asyncio.gather(
        repos.jobs.list_for_workspace(workspace.id),
        repos.documents.list_for_workspace(workspace.id, per_page=8),
    )
    book_price = float(await build_settings_service(repos).get("billing.book_price_usd", 7.0))
    active = [
        j
        for j in jobs
        if j.status in {"queued", "preparing", "parsing", "segmenting", "translating", "finalizing"}
    ]
    completed = [j for j in jobs if j.status == "completed"]
    return render(
        request,
        "pages/app/dashboard.html",
        {
            "user": user,
            "workspace": workspace,
            "jobs": jobs[:8],
            "documents": documents[:8],
            "active_count": len(active),
            "completed_count": len(completed),
            "book_price": book_price,
        },
    )


@router.get("/translations")
async def translations(request: Request, workspace: WorkspaceDep, repos: ReposDep) -> Response:
    jobs = await repos.jobs.list_for_workspace(workspace.id)
    return render(request, "pages/app/translations.html", {"jobs": jobs})


@router.get("/documents")
async def documents(request: Request, workspace: WorkspaceDep, repos: ReposDep) -> Response:
    docs = await repos.documents.list_for_workspace(workspace.id)
    return render(request, "pages/app/documents.html", {"documents": docs})


@router.get("/documents/{document_id}")
async def document_detail(
    request: Request, document_id: str, workspace: WorkspaceDep, repos: ReposDep
) -> Response:
    document = await repos.documents.get(document_id)
    if document.workspace != workspace.id:
        raise NotFoundError("Document not found.")
    return render(request, "pages/app/document_detail.html", {"document": document})


@router.get("/documents/{document_id}/source")
async def download_source(
    document_id: str, request: Request, workspace: WorkspaceDep, repos: ReposDep
) -> Response:
    document = await repos.documents.get(document_id)
    if document.workspace != workspace.id or not document.storage_key:
        raise NotFoundError("Document not found.")
    storage = get_ctx(request).storage
    key = document.storage_key
    filename = document.original_filename or f"{document.id}.{document.extension or 'bin'}"

    async def _iter() -> AsyncIterator[bytes]:
        async for chunk in storage.stream(key):
            yield chunk

    return StreamingResponse(
        _iter(),
        media_type=document.mime_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
