"""Glossary management."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import HTMLResponse

from app.api.dependencies import CsrfProtected, ReposDep, WorkspaceDep
from app.exceptions import NotFoundError
from app.schemas.knowledge import Glossary
from app.web.templating import render

router = APIRouter(prefix="/app/glossaries", tags=["glossaries"])


@router.get("")
async def list_glossaries(request: Request, workspace: WorkspaceDep, repos: ReposDep) -> Response:
    glossaries = await repos.glossaries.list_for_workspace(workspace.id)
    return render(request, "pages/app/glossaries.html", {"glossaries": glossaries})


@router.get("/new")
async def new_glossary(request: Request, workspace: WorkspaceDep, repos: ReposDep) -> Response:
    return render(request, "pages/app/glossary_new.html", {})


@router.post("")
async def create_glossary(
    request: Request,
    workspace: WorkspaceDep,
    repos: ReposDep,
    _csrf: CsrfProtected,
    name: Annotated[str, Form()],
    description: Annotated[str, Form()] = "",
) -> Response:
    glossary = await repos.glossaries.create(
        {
            "workspace": workspace.id,
            "name": name.strip()[:200],
            "description": description.strip()[:2000] or None,
            "enabled": True,
        }
    )
    response = Response(status_code=200)
    response.headers["HX-Redirect"] = f"/app/glossaries/{glossary.id}"
    return response


@router.get("/{glossary_id}")
async def glossary_detail(
    request: Request, glossary_id: str, workspace: WorkspaceDep, repos: ReposDep
) -> Response:
    glossary = await _owned(repos, workspace.id, glossary_id)
    terms = await repos.glossary_terms.list(filter=f'glossary = "{glossary.id}"')
    return render(request, "pages/app/glossary_detail.html", {"glossary": glossary, "terms": terms})


@router.post("/{glossary_id}/terms")
async def add_term(
    request: Request,
    glossary_id: str,
    workspace: WorkspaceDep,
    repos: ReposDep,
    _csrf: CsrfProtected,
    source_language: Annotated[str, Form()],
    target_language: Annotated[str, Form()],
    source_term: Annotated[str, Form()],
    target_term: Annotated[str, Form()],
    preferred: Annotated[str, Form()] = "",
    forbidden: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
) -> Response:
    glossary = await _owned(repos, workspace.id, glossary_id)
    term = await repos.glossary_terms.create(
        {
            "glossary": glossary.id,
            "source_language": source_language,
            "target_language": target_language,
            "source_term": source_term.strip()[:500],
            "target_term": target_term.strip()[:500],
            "preferred": bool(preferred),
            "forbidden": bool(forbidden),
            "notes": notes.strip()[:2000] or None,
        }
    )
    return render(request, "partials/glossary_term_row.html", {"glossary": glossary, "term": term})


@router.post("/{glossary_id}/terms/{term_id}/delete")
async def delete_term(
    request: Request,
    glossary_id: str,
    term_id: str,
    workspace: WorkspaceDep,
    repos: ReposDep,
    _csrf: CsrfProtected,
) -> Response:
    glossary = await _owned(repos, workspace.id, glossary_id)
    term = await repos.glossary_terms.get(term_id)
    if term.glossary == glossary.id:
        await repos.glossary_terms.delete(term.id)
    return HTMLResponse("")


async def _owned(repos: ReposDep, workspace_id: str, glossary_id: str) -> Glossary:
    glossary = await repos.glossaries.get(glossary_id)
    if glossary.workspace != workspace_id:
        raise NotFoundError("Glossary not found.")
    return glossary
