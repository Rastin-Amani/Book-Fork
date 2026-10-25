"""Translation memory and settings pages."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request, Response

from app.api.dependencies import ReposDep, WorkspaceDep
from app.language.registry import PocketBaseLanguageRegistry
from app.settings.service import SettingsService
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
    languages, variants = await asyncio.gather(
        PocketBaseLanguageRegistry(repos.languages).list(),
        repos.language_variants.list(per_page=500),
    )
    return render(
        request, "pages/app/settings_languages.html", {"languages": languages, "variants": variants}
    )


@router.get("/settings/profiles")
async def settings_profiles(request: Request, workspace: WorkspaceDep, repos: ReposDep) -> Response:
    profiles = await repos.profiles.list_available(workspace.id)
    return render(request, "pages/app/settings_profiles.html", {"profiles": profiles})


@router.get("/settings/billing")
async def settings_billing(request: Request, workspace: WorkspaceDep, repos: ReposDep) -> Response:
    jobs, documents = await asyncio.gather(
        repos.jobs.list_for_workspace(workspace.id),
        repos.documents.list_for_workspace(workspace.id, per_page=500),
    )
    titles = {doc.id: doc.display_name or doc.original_filename for doc in documents}
    orders = []
    for job in jobs:
        order = (job.metadata or {}).get("order")
        if not isinstance(order, dict):
            continue
        orders.append(
            {
                "job": job,
                "book": titles.get(job.document) or job.document,
                "pages": int(order.get("pages") or 0),
                "blocks": int(order.get("blocks") or 0),
                "amount": float(order.get("amount") or 0.0),
                "currency": str(order.get("currency") or "USD"),
                "status": _order_status(job, order),
            }
        )
    settings = SettingsService(repos.settings)
    return render(
        request,
        "pages/app/settings_billing.html",
        {
            "orders": orders[:50],
            "book_price": float(await settings.get("billing.book_price_usd", 7.0)),
            "pages_per_block": int(await settings.get("billing.pages_per_block", 1000)),
            "total": sum(order["amount"] for order in orders if order["status"] == "Completed"),
        },
    )


def _order_status(job: object, order: dict[str, object]) -> str:
    if order.get("billing_mode") == "own_api":
        return "Free"
    status = str(getattr(job, "status", "")).rsplit(".", 1)[-1]
    if status in {"failed", "cancelled", "cancelling"}:
        return "No charge"
    if status == "completed":
        return "Completed"
    return "In progress"
