"""Customer billing pages and the Gumroad webhook.

Every state-changing route requires authentication, CSRF, and workspace
ownership. The webhook is the only unauthenticated billing endpoint: it checks
the local callback secret, then re-reads the sale or subscription from Gumroad
before anything is fulfilled.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.dependencies import (
    CsrfProtected,
    CurrentUser,
    ReposDep,
    WorkspaceDep,
    get_ctx,
)
from app.api.repositories import build_repositories
from app.api.runtime import build_billing_service, build_settings_service
from app.billing.payments.base import InvalidWebhookError, WebhookPayloadError
from app.billing.service import BillingService, FreeAllowance
from app.exceptions import (
    BookForkError,
    ConfigurationError,
    NotFoundError,
    UpstreamError,
    ValidationError,
)
from app.observability.events import BILLING_SIGNATURE_FAILED, emit
from app.schemas.billing import BillingInvoice
from app.schemas.translation import TranslationJob
from app.web.templating import render

router = APIRouter(prefix="/app/settings/billing", tags=["billing"])
webhook_router = APIRouter(prefix="/api/webhooks", tags=["billing"])

_WEBHOOK_MAX_BYTES = 256 * 1024


@router.get("")
async def billing_overview(
    request: Request,
    user: CurrentUser,
    workspace: WorkspaceDep,
    repos: ReposDep,
) -> Response:
    ctx = get_ctx(request)
    settings = build_settings_service(repos)
    billing = await build_billing_service(ctx, repos, settings)
    invoices, jobs, documents = await asyncio.gather(
        repos.invoices.list_for_workspace(workspace.id),
        repos.jobs.list_for_workspace(workspace.id),
        repos.documents.list_for_workspace(workspace.id, per_page=500),
    )
    allowance = (
        await billing.allowance(workspace.id)
        if billing.enabled
        else FreeAllowance(total=0, used=0, remaining=0)
    )
    by_job = {invoice.job: invoice for invoice in invoices if invoice.job}
    titles = {doc.id: doc.display_name or doc.original_filename for doc in documents}
    orders = [_order_row(job, by_job.get(job.id), titles) for job in jobs if _has_order(job)]
    return render(
        request,
        "pages/app/settings_billing.html",
        {
            "orders": orders,
            "invoices": invoices,
            "billing_enabled": billing.enabled,
            "allowance": allowance,
            "book_price": float(await settings.get("billing.book_price_usd", 7.0)),
            "pages_per_block": int(await settings.get("billing.pages_per_block", 1000)),
            "total": sum(
                order["amount"] for order in orders if order["status"] == "paid" and order["amount"]
            ),
        },
    )


@router.get("/invoices/{invoice_id}")
async def invoice_page(
    request: Request,
    invoice_id: str,
    user: CurrentUser,
    workspace: WorkspaceDep,
    repos: ReposDep,
) -> Response:
    invoice = await _owned_invoice(repos, workspace.id, invoice_id)
    billing = await build_billing_service(get_ctx(request), repos)
    error = None
    if (
        billing.enabled
        and (invoice.provider_reference or invoice.correlation_token)
        and invoice.status in ("pending", "awaiting_payment", "partially_paid")
    ):
        try:
            invoice = await billing.reconcile(invoice)
        except UpstreamError:
            error = "The provider could not be reached. The invoice stays pending."
    job = await _job_or_none(repos, invoice.job)
    return render(
        request,
        "pages/app/billing_invoice.html",
        {
            "invoice": invoice,
            "job": job,
            "error": error,
            "billing_enabled": billing.enabled,
            "poll_url": _poll_url(invoice),
        },
    )


@router.get("/invoices/{invoice_id}/status")
async def invoice_status(
    request: Request,
    invoice_id: str,
    user: CurrentUser,
    workspace: WorkspaceDep,
    repos: ReposDep,
) -> Response:
    invoice = await _owned_invoice(repos, workspace.id, invoice_id)
    job = await _job_or_none(repos, invoice.job)
    return render(
        request,
        "partials/invoice_status.html",
        {
            "invoice": invoice,
            "job": job,
            "billing_enabled": get_ctx(request).settings.billing_enabled,
            "poll_url": _poll_url(invoice),
        },
    )


@router.post("/invoices/{invoice_id}/checkout")
async def invoice_checkout(
    request: Request,
    invoice_id: str,
    user: CurrentUser,
    workspace: WorkspaceDep,
    repos: ReposDep,
    _csrf: CsrfProtected,
) -> Response:
    invoice = await _owned_invoice(repos, workspace.id, invoice_id)
    billing = await build_billing_service(get_ctx(request), repos)
    try:
        invoice = await billing.create_checkout(invoice, user_email=user.email)
    except BookForkError as exc:
        job = await _job_or_none(repos, invoice.job)
        return render(
            request,
            "pages/app/billing_invoice.html",
            {
                "invoice": invoice,
                "job": job,
                "error": exc.message,
                "billing_enabled": billing.enabled,
                "poll_url": _poll_url(invoice),
            },
            status_code=exc.status_code,
        )
    if not invoice.checkout_url:
        raise UpstreamError("The payment provider did not return a checkout URL.")
    return _redirect(request, invoice.checkout_url)


@router.post("/invoices/{invoice_id}/reconcile")
async def invoice_reconcile(
    request: Request,
    invoice_id: str,
    user: CurrentUser,
    workspace: WorkspaceDep,
    repos: ReposDep,
    _csrf: CsrfProtected,
) -> Response:
    invoice = await _owned_invoice(repos, workspace.id, invoice_id)
    billing = await build_billing_service(get_ctx(request), repos)
    error = None
    try:
        invoice = await billing.reconcile(invoice)
    except BookForkError as exc:
        error = exc.message
    job = await _job_or_none(repos, invoice.job)
    return render(
        request,
        "partials/invoice_status.html",
        {
            "invoice": invoice,
            "job": job,
            "error": error,
            "billing_enabled": billing.enabled,
            "poll_url": _poll_url(invoice),
        },
    )


# -- webhook -----------------------------------------------------------------
@webhook_router.post("/gumroad")
async def gumroad_webhook(request: Request) -> Response:
    ctx = get_ctx(request)
    content_type = request.headers.get("content-type", "").lower()
    if "application/x-www-form-urlencoded" not in content_type:
        return JSONResponse({"message": "Unsupported content type."}, status_code=415)
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > _WEBHOOK_MAX_BYTES:
        return JSONResponse({"message": "Payload too large."}, status_code=413)
    # Stream with a hard bound: Content-Length is advisory and may be absent.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > _WEBHOOK_MAX_BYTES:
            return JSONResponse({"message": "Payload too large."}, status_code=413)
    raw = bytes(body)

    token = await ctx.ensure_service_token()
    if not ctx.settings.billing_enabled or token is None or ctx.payments is None:
        return JSONResponse({"message": "Billing is not configured."}, status_code=503)

    writes = build_repositories(ctx.pocketbase, token=token)
    billing: BillingService = await build_billing_service(ctx, writes)
    try:
        await billing.handle_webhook(
            raw,
            dict(request.headers),
            callback_secret=request.query_params.get("secret"),
        )
    except InvalidWebhookError:
        emit(BILLING_SIGNATURE_FAILED, path=request.url.path)
        return JSONResponse({"message": "Invalid webhook secret."}, status_code=401)
    except WebhookPayloadError:
        return JSONResponse({"message": "Invalid payload."}, status_code=400)
    except ValidationError:
        return JSONResponse({"message": "Invalid payload."}, status_code=400)
    except ConfigurationError:
        return JSONResponse({"message": "Billing is not configured."}, status_code=503)
    except BookForkError:
        # A temporary storage/provider failure is retryable by Gumroad.
        return JSONResponse({"message": "Temporary failure."}, status_code=500)
    return JSONResponse({"received": True})


# -- helpers -----------------------------------------------------------------
def _has_order(job: TranslationJob) -> bool:
    order = (job.metadata or {}).get("order")
    return isinstance(order, dict)


def _order_row(
    job: TranslationJob,
    invoice: BillingInvoice | None,
    titles: Mapping[str, str | None],
) -> dict[str, object]:
    order = (job.metadata or {}).get("order")
    order = order if isinstance(order, dict) else {}
    status = invoice.status if invoice is not None else _legacy_status(job, order)
    return {
        "job": job,
        "invoice": invoice,
        "book": titles.get(job.document) or job.document,
        "pages": int(order.get("pages") or 0),
        "blocks": int(order.get("blocks") or 0),
        "amount": float(order.get("amount") or 0.0),
        "currency": str(order.get("currency") or "USD"),
        "status": status,
    }


def _legacy_status(job: TranslationJob, order: dict[str, object]) -> str:
    if order.get("billing_mode") == "own_api":
        return "Free"
    status = str(job.status).rsplit(".", 1)[-1]
    if status in {"failed", "cancelled", "cancelling"}:
        return "No charge"
    if status == "completed":
        return "Completed"
    return "In progress"


async def _owned_invoice(repos: ReposDep, workspace_id: str, invoice_id: str) -> BillingInvoice:
    invoice = await repos.invoices.get(invoice_id)
    if invoice.workspace != workspace_id:
        raise NotFoundError("Invoice not found.")
    return invoice


def _poll_url(invoice: BillingInvoice) -> str | None:
    if invoice.status in ("pending", "awaiting_payment", "partially_paid"):
        return f"/app/settings/billing/invoices/{invoice.id}/status"
    return None


async def _job_or_none(repos: ReposDep, job_id: str | None) -> TranslationJob | None:
    if not job_id:
        return None
    try:
        return await repos.jobs.get(job_id)
    except NotFoundError:
        return None


def _redirect(request: Request, location: str) -> Response:
    if request.headers.get("HX-Request", "").lower() == "true":
        response = Response(status_code=200)
        response.headers["HX-Redirect"] = location
        return response
    return RedirectResponse(location, status_code=303)
