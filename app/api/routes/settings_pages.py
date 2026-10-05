"""Translation memory and settings pages."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request, Response

from app.api.dependencies import ReposDep, WorkspaceDep
from app.language.registry import PocketBaseLanguageRegistry
from app.web.templating import render

router = APIRouter(prefix="/app", tags=["settings"])


@router.get("/translation-memory")
async def translation_memory(
    request: Request, workspace: WorkspaceDep, repos: ReposDep
) -> Response:
    entries = await repos.memory.list_for_workspace(workspace.id)
    return render(request, "pages/app/memory.html", {"entries": entries[:200]})


@router.get("/settings")
async def settings_hub(request: Request, workspace: WorkspaceDep, repos: ReposDep) -> Response:
    return render(request, "pages/app/settings.html", {"workspace": workspace})


@router.get("/settings/languages")
async def settings_languages(
    request: Request, workspace: WorkspaceDep, repos: ReposDep
) -> Response:
    languages = await PocketBaseLanguageRegistry(repos.languages).list()
    variants = await repos.language_variants.list(per_page=500)
    return render(
        request, "pages/app/settings_languages.html", {"languages": languages, "variants": variants}
    )


@router.get("/settings/profiles")
async def settings_profiles(request: Request, workspace: WorkspaceDep, repos: ReposDep) -> Response:
    profiles = await repos.profiles.list_available(workspace.id)
    return render(request, "pages/app/settings_profiles.html", {"profiles": profiles})


@router.get("/settings/billing")
async def settings_billing(request: Request, workspace: WorkspaceDep, repos: ReposDep) -> Response:
    wallet = await repos.wallets.get_for_workspace(workspace.id)
    if wallet is not None:
        transactions, usage = await asyncio.gather(
            repos.transactions.list_for_wallet(wallet.id),
            repos.usage_events.list_for_workspace(workspace.id),
        )
    else:
        transactions, usage = [], []
    return render(
        request,
        "pages/app/settings_billing.html",
        {"wallet": wallet, "transactions": transactions[:50], "usage": usage[:50]},
    )
