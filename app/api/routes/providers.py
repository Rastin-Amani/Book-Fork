"""Provider connection management (user-owned and managed)."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import HTMLResponse

from app.api.dependencies import (
    CsrfProtected,
    ProviderTestRateLimited,
    ReposDep,
    WorkspaceDep,
    get_ctx,
)
from app.api.runtime import build_credential_service, build_provider_runtime
from app.observability.events import PROVIDER_CONNECTION_TESTED, emit
from app.providers.testing import ProviderConnectionTester
from app.web.templating import render

router = APIRouter(prefix="/app/providers", tags=["providers"])


@router.get("")
async def list_providers(request: Request, workspace: WorkspaceDep, repos: ReposDep) -> Response:
    connections, providers = await asyncio.gather(
        repos.connections.list_for_workspace(workspace.id),
        repos.providers.list(),
    )
    return render(
        request,
        "pages/app/providers.html",
        {
            "connections": connections,
            "catalog": [p for p in providers if p.enabled],
            "providers_by_id": {p.id: p for p in providers},
        },
    )


@router.get("/new")
async def new_provider(request: Request, workspace: WorkspaceDep, repos: ReposDep) -> Response:
    catalog = await repos.providers.list_enabled()
    return render(request, "pages/app/provider_new.html", {"catalog": catalog})


@router.post("")
async def create_provider(
    request: Request,
    workspace: WorkspaceDep,
    repos: ReposDep,
    _csrf: CsrfProtected,
    name: Annotated[str, Form()],
    provider_id: Annotated[str, Form()],
    base_url: Annotated[str, Form()] = "",
    api_key: Annotated[str, Form()] = "",
    default_model: Annotated[str, Form()] = "",
    billing_mode: Annotated[str, Form()] = "own_api",
) -> Response:
    connection = await repos.connections.create(
        {
            "workspace": workspace.id,
            "provider": provider_id,
            "name": name.strip()[:200],
            "base_url": base_url.strip() or None,
            "auth_type": "api_key",
            "billing_mode": billing_mode,
            "enabled": True,
            "config": {"default_model": default_model.strip()} if default_model.strip() else {},
        }
    )
    if api_key.strip():
        ctx = get_ctx(request)
        service_token = await ctx.ensure_service_token()
        credentials = build_credential_service(ctx.pocketbase, ctx.settings, token=service_token)
        await credentials.store(connection.id, api_key.strip())
    response = Response(status_code=200)
    response.headers["HX-Redirect"] = "/app/providers"
    return response


@router.post("/{connection_id}/credential")
async def update_credential(
    request: Request,
    connection_id: str,
    workspace: WorkspaceDep,
    repos: ReposDep,
    _csrf: CsrfProtected,
    api_key: Annotated[str, Form()],
) -> Response:
    """Replace a connection's API key without recreating the connection.

    Jobs keep their provider-connection id in their snapshot, so deleting and
    re-adding a connection orphans every job pinned to it.
    """
    connection = await repos.connections.get(connection_id)
    if connection.workspace != workspace.id:
        return HTMLResponse('<span class="badge badge-error">Not found</span>', status_code=404)
    key = api_key.strip()
    if not key:
        return HTMLResponse(
            '<span class="badge badge-error">API key is required</span>', status_code=422
        )
    ctx = get_ctx(request)
    service_token = await ctx.ensure_service_token()
    credentials = build_credential_service(ctx.pocketbase, ctx.settings, token=service_token)
    await credentials.store(connection.id, key)
    return render(request, "partials/provider_row.html", {"connection": connection})


@router.post("/{connection_id}/test")
async def test_provider(
    request: Request,
    connection_id: str,
    workspace: WorkspaceDep,
    repos: ReposDep,
    _csrf: CsrfProtected,
    _rate: ProviderTestRateLimited,
) -> Response:
    connection = await repos.connections.get(connection_id)
    if connection.workspace != workspace.id:
        return HTMLResponse('<span class="badge badge-error">Not found</span>', status_code=404)
    ctx = get_ctx(request)
    service_token = await ctx.ensure_service_token()
    runtime = build_provider_runtime(
        client=ctx.pocketbase,
        settings=ctx.settings,
        connections=repos.connections,
        providers=repos.providers,
        token=None,
        service_token=service_token,
    )
    result = await ProviderConnectionTester(runtime).test(
        connection_id=connection.id,
        provider_id=connection.provider,
        model_identifier=(connection.config or {}).get("default_model"),
        allow_private=bool((connection.config or {}).get("allow_private")),
    )
    emit(
        PROVIDER_CONNECTION_TESTED,
        connection_id=connection.id,
        ok=bool(getattr(result, "ok", False)),
    )
    return render(request, "partials/connection_test.html", {"result": result})


@router.post("/{connection_id}/toggle")
async def toggle_provider(
    request: Request,
    connection_id: str,
    workspace: WorkspaceDep,
    repos: ReposDep,
    _csrf: CsrfProtected,
) -> Response:
    connection = await repos.connections.get(connection_id)
    if connection.workspace != workspace.id:
        return HTMLResponse("", status_code=404)
    connection = await repos.connections.update(connection.id, {"enabled": not connection.enabled})
    return render(request, "partials/provider_row.html", {"connection": connection})


@router.post("/{connection_id}/delete")
async def delete_provider(
    request: Request,
    connection_id: str,
    workspace: WorkspaceDep,
    repos: ReposDep,
    _csrf: CsrfProtected,
) -> Response:
    connection = await repos.connections.get(connection_id)
    if connection.workspace == workspace.id:
        await repos.connections.delete(connection.id)
    return HTMLResponse("")
