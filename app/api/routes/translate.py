"""New-translation workflow, job pages, actions and review."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, File, Form, Request, Response, UploadFile
from fastapi.responses import StreamingResponse

from app.api.dependencies import (
    CsrfProtected,
    CtxDep,
    CurrentUser,
    ReposDep,
    RetryRateLimited,
    TranslationRateLimited,
    WorkspaceDep,
    get_ctx,
)
from app.api.runtime import (
    build_ingest_service,
    build_job_service,
    build_limit_service,
    build_settings_service,
)
from app.documents.adapters.base import DocumentType, ParseOptions
from app.documents.service import DocumentEngine
from app.exceptions import NotFoundError, ValidationError
from app.language.detector import LangidDetector
from app.language.registry import PocketBaseLanguageRegistry
from app.observability.events import JOB_CREATED, UPLOAD, emit
from app.schemas.documents import Document
from app.schemas.translation import TranslationJob
from app.web.templating import render

router = APIRouter(prefix="/app/translations", tags=["translations"])
_detector = LangidDetector()


async def _new_form_context(
    repos: ReposDep, workspace_id: str, request: Request
) -> dict[str, object]:
    registry = PocketBaseLanguageRegistry(repos.languages)
    languages, profiles, connections, documents = await asyncio.gather(
        registry.list(),
        repos.profiles.list_available(workspace_id),
        repos.connections.list_for_workspace(workspace_id),
        repos.documents.list_for_workspace(workspace_id),
    )
    return {
        "languages": languages,
        "profiles": profiles,
        "connections": [c for c in connections if c.enabled],
        "documents": [d for d in documents if d.status in {"ready", "uploaded", "parsed"}],
    }


@router.get("/new")
async def new_translation(request: Request, workspace: WorkspaceDep, repos: ReposDep) -> Response:
    context = await _new_form_context(repos, workspace.id, request)
    return render(request, "pages/app/translation_new.html", context)


@router.post("/estimate")
async def estimate(
    request: Request,
    workspace: WorkspaceDep,
    repos: ReposDep,
    _csrf: CsrfProtected,
    document_id: Annotated[str, Form()] = "",
    source_language: Annotated[str, Form()] = "",
    target_language: Annotated[str, Form()] = "",
    connection_id: Annotated[str, Form()] = "",
    quality_mode: Annotated[str, Form()] = "",
) -> Response:
    if target_language in ("", "auto"):
        return render(
            request, "partials/estimate_error.html", {"message": "Choose a target language."}
        )
    if not document_id:
        return render(request, "partials/estimate_error.html", {"message": "Choose a document."})
    document = await repos.documents.get(document_id)
    if document.workspace != workspace.id:
        raise NotFoundError("Document not found.")
    source = await _resolve_source(request, repos, workspace.id, document, source_language)
    service = build_job_service(repos, build_settings_service(repos))
    try:
        plan = await service.build_plan(
            workspace_id=workspace.id,
            source_language=source,
            target_language=target_language,
            connection_id=connection_id or None,
            quality_mode=quality_mode or None,
        )
        view = await service.estimate(document=document, plan=plan)
    except ValidationError as exc:
        return render(request, "partials/estimate_error.html", {"message": exc.message})
    return render(
        request,
        "partials/estimate.html",
        {"estimate": view, "source": source, "target": target_language},
    )


@router.post("")
async def create_translation(
    request: Request,
    user: CurrentUser,
    workspace: WorkspaceDep,
    repos: ReposDep,
    _csrf: CsrfProtected,
    _rate: TranslationRateLimited,
    document_id: Annotated[str, Form()] = "",
    source_language: Annotated[str, Form()] = "",
    target_language: Annotated[str, Form()] = "",
    connection_id: Annotated[str, Form()] = "",
    quality_mode: Annotated[str, Form()] = "",
    profile_id: Annotated[str, Form()] = "",
    persist_memory: Annotated[str, Form()] = "",
    upload: Annotated[UploadFile | None, File()] = None,
) -> Response:
    ctx = get_ctx(request)
    settings = build_settings_service(repos)
    limits = build_limit_service(
        repos, settings, fallback_upload_bytes=ctx.settings.max_request_bytes
    )
    if upload is not None and upload.filename:
        data = await upload.read()
        await limits.check_file_size(len(data))
        await limits.check_upload(workspace.id)
        ingest = build_ingest_service(repos, ctx.storage, ctx.settings)
        document = await ingest.ingest(
            workspace_id=workspace.id,
            created_by=user.id,
            filename=upload.filename,
            data=data,
            content_type=upload.content_type,
        )
        emit(UPLOAD, workspace_id=workspace.id, document_id=document.id, size=len(data))
    elif document_id:
        document = await repos.documents.get(document_id)
        if document.workspace != workspace.id:
            raise NotFoundError("Document not found.")
    else:
        return render(
            request, "partials/estimate_error.html", {"message": "Upload a document to continue."}
        )

    await limits.check_job_create(workspace.id)
    source = await _resolve_source(request, repos, workspace.id, document, source_language)
    job_service = build_job_service(repos, settings)
    plan = await job_service.build_plan(
        workspace_id=workspace.id,
        source_language=source,
        target_language=target_language,
        profile_id=profile_id or None,
        connection_id=connection_id or None,
        quality_mode=quality_mode or None,
    )
    job = await job_service.create(
        workspace_id=workspace.id,
        created_by=user.id,
        document=document,
        plan=plan,
        persist_memory=bool(persist_memory),
    )
    emit(JOB_CREATED, workspace_id=workspace.id, job_id=job.id, target_language=target_language)
    response = Response(status_code=200)
    response.headers["HX-Redirect"] = f"/app/translations/{job.id}"
    return response


@router.get("/{job_id}")
async def job_page(
    request: Request, job_id: str, workspace: WorkspaceDep, repos: ReposDep
) -> Response:
    job = await _owned_job(repos, workspace.id, job_id)
    document = await repos.documents.get(job.document)
    # The job page renders status + progress only; segments and events are
    # loaded lazily by the review page / status poll. Fetching them here cost a
    # paged round trip per 500 rows on every view for data nothing rendered.
    return render(
        request,
        "pages/app/job.html",
        {"job": job, "document": document},
    )


@router.get("/{job_id}/status")
async def job_status(
    request: Request, job_id: str, workspace: WorkspaceDep, repos: ReposDep
) -> Response:
    job = await _owned_job(repos, workspace.id, job_id)
    return render(request, "partials/job_status.html", {"job": job})


@router.post("/{job_id}/cancel")
async def cancel_job(
    request: Request, job_id: str, workspace: WorkspaceDep, repos: ReposDep, _csrf: CsrfProtected
) -> Response:
    job = await _owned_job(repos, workspace.id, job_id)
    job = await repos.jobs.update(job.id, {"cancellation_requested": True})
    return render(request, "partials/job_status.html", {"job": job})


@router.post("/{job_id}/retry")
async def retry_job(
    request: Request,
    job_id: str,
    workspace: WorkspaceDep,
    repos: ReposDep,
    ctx: CtxDep,
    _csrf: CsrfProtected,
    _rate: RetryRateLimited,
) -> Response:
    job = await _owned_job(repos, workspace.id, job_id)
    limits = build_limit_service(
        repos, build_settings_service(repos), fallback_upload_bytes=ctx.settings.max_request_bytes
    )
    await limits.check_retry(job)
    metadata = dict(job.metadata or {})
    metadata["retry_count"] = int(metadata.get("retry_count", 0)) + 1
    job = await repos.jobs.update(
        job.id,
        {
            "status": "queued",
            "cancellation_requested": False,
            "error_code": None,
            "error_message": None,
            "metadata": metadata,
        },
    )
    return render(request, "partials/job_status.html", {"job": job})


@router.get("/{job_id}/download")
async def download_output(
    job_id: str,
    request: Request,
    workspace: WorkspaceDep,
    repos: ReposDep,
    format: str | None = None,
) -> Response:
    job = await _owned_job(repos, workspace.id, job_id)
    entry = _select_output(job, format)
    if entry is None:
        raise NotFoundError("No output is available yet.")

    document = await repos.documents.get(job.document)
    storage = get_ctx(request).storage
    extension = str(entry.get("extension") or "").lstrip(".")
    media_type = str(entry.get("mime") or "application/octet-stream")
    filename = _output_filename(document, job, extension or "bin", format)

    key = str(entry["key"])

    async def _iter() -> AsyncIterator[bytes]:
        async for chunk in storage.stream(key):
            yield chunk

    return StreamingResponse(
        _iter(),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


_OUTPUT_PRIORITY = ("epub", "pdf")


def _select_output(job: TranslationJob, requested: str | None) -> dict[str, object] | None:
    outputs = (job.metadata or {}).get("outputs")
    outputs = outputs if isinstance(outputs, dict) else {}
    if requested and requested in outputs:
        return dict(outputs[requested])
    for name in _OUTPUT_PRIORITY:
        if name in outputs:
            return dict(outputs[name])
    for value in outputs.values():
        if isinstance(value, dict) and value.get("key"):
            return dict(value)
    if job.output_storage_key:
        extension = (job.output_mime_type or "").split("/")[-1]
        return {
            "key": job.output_storage_key,
            "mime": job.output_mime_type,
            "extension": extension,
        }
    return None


def _output_filename(
    document: Document, job: TranslationJob, extension: str, format: str | None
) -> str:
    base = document.display_name or document.original_filename or f"translated-{job.id}"
    if base.lower().endswith(f".{extension.lower()}"):
        base = base[: -(len(extension) + 1)]
    language = job.target_language or "target"
    safe = "".join(char for char in base if char.isalnum() or char in " -_.").strip()
    return f"{safe or 'translated'}-{language}.{extension}"


@router.get("/{job_id}/review")
async def review(
    request: Request, job_id: str, workspace: WorkspaceDep, repos: ReposDep
) -> Response:
    # Authorization (job ownership) and the segment page are independent; the
    # ownership read is still awaited before rendering, so an unauthorized
    # caller gets the 404 and the segment fetch is discarded. Saves a round
    # trip on every review open.
    job, segments = await asyncio.gather(
        _owned_job(repos, workspace.id, job_id),
        repos.segments.list_for_job(job_id),
    )
    return render(request, "pages/app/review.html", {"job": job, "segments": segments})


@router.post("/{job_id}/segments/{segment_id}")
async def update_segment(
    request: Request,
    job_id: str,
    segment_id: str,
    workspace: WorkspaceDep,
    repos: ReposDep,
    _csrf: CsrfProtected,
    translated_text: Annotated[str, Form()] = "",
    approve: Annotated[str, Form()] = "",
) -> Response:
    job = await _owned_job(repos, workspace.id, job_id)
    segment = await repos.segments.get(segment_id)
    if segment.job != job.id:
        raise NotFoundError("Segment not found.")
    fields: dict[str, object] = {"translated_text": translated_text}
    if approve:
        fields["status"] = "validated"
    segment = await repos.segments.update(
        segment.id,
        fields,
    )
    return render(request, "partials/segment_row.html", {"job": job, "segment": segment})


async def _owned_job(repos: ReposDep, workspace_id: str, job_id: str) -> TranslationJob:
    job = await repos.jobs.get(job_id)
    if job.workspace != workspace_id:
        raise NotFoundError("Translation not found.")
    return job


async def _resolve_source(
    request: Request,
    repos: ReposDep,
    workspace_id: str,
    document: Document,
    source_language: str,
) -> str:
    if source_language and source_language != "auto":
        return source_language
    if document.source_language:
        return document.source_language

    if not document.storage_key:
        raise ValidationError("The document has no stored source.")
    key = document.storage_key
    engine = DocumentEngine(temp_root=get_ctx(request).settings.document_temp_root)
    async with engine.materialize(get_ctx(request).storage, key) as path:
        result = await engine.parse_file(
            path,
            document_type=DocumentType(document.document_type or "pdf"),
            options=ParseOptions(document_id=document.id),
        )
    sample = " ".join(block.plain_text for block in result.document.text_blocks())[:8000]
    detection = await _detector.detect(sample)
    if detection is None or not detection.language:
        raise ValidationError("Could not detect the source language; choose one explicitly.")
    await repos.documents.update(
        document.id,
        {
            "detected_language": detection.language,
            "detected_confidence": detection.confidence,
            "source_language": detection.language,
        },
    )
    return detection.language
