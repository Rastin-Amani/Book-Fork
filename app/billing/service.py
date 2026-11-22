"""Billing service: invoices, free allowance, checkout, and fulfillment.

One managed translation job is one book order. The job is created in
``awaiting_payment`` and is only queued for the worker after a verified payment
(or an explicitly configured free allowance) grants the entitlement. A failed,
partial, cancelled, or amount-mismatched payment never queues the job.

Gumroad notifications are treated as hints: every sale or subscription is
re-read from the Gumroad API before an invoice changes. A hosted checkout is
correlated by a high-entropy token stored on the invoice and carried in a
Gumroad custom field; email and amount alone are never enough to match a sale.
"""

from __future__ import annotations

import hmac
import secrets
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from app.billing.payments.base import (
    CheckoutRequest,
    PaymentProvider,
    ProviderEventKind,
    ProviderNotification,
    ProviderPayment,
    ProviderState,
    ProviderSubscription,
)
from app.exceptions import (
    ConfigurationError,
    ConflictError,
    UpstreamError,
    ValidationError,
)
from app.logging import get_logger
from app.observability.events import (
    BILLING_CHECKOUT_CREATED,
    BILLING_DISPUTED,
    BILLING_FULFILLED,
    BILLING_FULFILLMENT_FAILED,
    BILLING_INVOICE_CREATED,
    BILLING_PAYMENT_RECEIVED,
    BILLING_RECONCILED,
    BILLING_REFUNDED,
    emit,
)
from app.repositories.billing import (
    BillingEventRepository,
    BillingFreeClaimRepository,
    BillingInvoiceRepository,
)
from app.repositories.translation import TranslationJobRepository
from app.schemas.billing import (
    BillingInvoice,
    InvoiceProvider,
    InvoiceStatus,
    ProductType,
)
from app.schemas.translation import TranslationJob
from app.settings.service import SettingsService

logger = get_logger(__name__)

KEY_FREE_MANAGED_BOOKS = "billing.free_managed_books"
KEY_CHECKOUT_EXPIRY_HOURS = "billing.checkout_expiry_hours"
KEY_CURRENCY = "billing.default_currency"

_AMOUNT_TOLERANCE = Decimal("0.01")
_PAID_STATUSES = (InvoiceStatus.PAID, InvoiceStatus.REFUNDED)
_OPEN_STATUSES = (
    InvoiceStatus.PENDING,
    InvoiceStatus.AWAITING_PAYMENT,
    InvoiceStatus.PARTIALLY_PAID,
    InvoiceStatus.REVIEW,
)
_EXPIRABLE_STATUSES = (
    InvoiceStatus.PENDING,
    InvoiceStatus.AWAITING_PAYMENT,
    InvoiceStatus.PARTIALLY_PAID,
)
_SALE_EVENTS = frozenset(
    {
        ProviderEventKind.SALE,
        ProviderEventKind.REFUND,
        ProviderEventKind.DISPUTE,
        ProviderEventKind.DISPUTE_WON,
    }
)
_MAX_RENEWALS = 20


@dataclass(frozen=True, slots=True)
class FreeAllowance:
    total: int
    used: int
    remaining: int


class BillingService:
    def __init__(
        self,
        *,
        invoices: BillingInvoiceRepository,
        events: BillingEventRepository,
        claims: BillingFreeClaimRepository,
        jobs: TranslationJobRepository,
        settings: SettingsService,
        provider: PaymentProvider | None,
        billing_enabled: bool,
    ) -> None:
        self._invoices = invoices
        self._events = events
        self._claims = claims
        self._jobs = jobs
        self._settings = settings
        self._provider = provider
        self._enabled = billing_enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    def requires_payment(self, billing_mode: str) -> bool:
        return self._enabled and billing_mode == "managed"

    async def allowance(self, workspace_id: str) -> FreeAllowance:
        total = _as_int(await self._settings.get(KEY_FREE_MANAGED_BOOKS, 0))
        used = await self._claims.count_for_workspace(
            workspace_id, kind=ProductType.MANAGED_BOOK.value
        )
        return FreeAllowance(total=max(0, total), used=used, remaining=max(0, total - used))

    # -- order start ---------------------------------------------------------
    async def start(
        self,
        *,
        job: TranslationJob,
        workspace_id: str,
        user_id: str,
    ) -> BillingInvoice | None:
        """Attach an invoice to an awaiting-payment job and grant free books.

        Returns the invoice. A paid (including free) invoice has already queued
        the job; a pending one must go through checkout first.
        """
        if job.status != "awaiting_payment":
            return None
        order = job.metadata.get("order") if isinstance(job.metadata, dict) else None
        order = order if isinstance(order, dict) else {}
        amount = _as_decimal(order.get("amount")) or Decimal("0")
        currency = str(order.get("currency") or await self._setting(KEY_CURRENCY, "USD"))

        invoice = await self._invoices.create(
            {
                "workspace": workspace_id,
                "created_by": user_id,
                "job": job.id,
                "reference": _invoice_reference(),
                "correlation_token": secrets.token_urlsafe(32),
                "product_type": ProductType.MANAGED_BOOK.value,
                "product_name": "Managed book translation",
                "amount": float(amount),
                "currency": currency,
                "status": InvoiceStatus.PENDING.value,
                "provider": InvoiceProvider.NONE.value,
                "product_snapshot": {
                    "order": order,
                    "target_language": job.target_language,
                    "source_language": job.source_language,
                    "document": job.document,
                },
            }
        )
        emit(
            BILLING_INVOICE_CREATED,
            invoice_id=invoice.id,
            workspace_id=workspace_id,
            job_id=job.id,
            amount=float(amount),
            currency=currency,
        )
        await self._attach_to_job(job, invoice)

        if amount <= 0:
            return await self._grant_free(invoice, job)

        allowance = await self.allowance(workspace_id)
        if allowance.remaining <= 0:
            return invoice

        claim = await self._claims.claim(
            workspace_id,
            kind=ProductType.MANAGED_BOOK.value,
            max_slots=allowance.total,
            job_id=job.id,
        )
        if claim is None:
            return invoice
        await self._claims.update(claim.id, {"invoice": invoice.id})
        return await self._grant_free(invoice, job)

    async def invoice_for_job(self, job_id: str) -> BillingInvoice | None:
        return await self._invoices.get_for_job(job_id)

    # -- checkout ------------------------------------------------------------
    async def create_checkout(
        self, invoice: BillingInvoice, *, user_email: str | None
    ) -> BillingInvoice:
        provider = self._require_provider()
        if invoice.provider == InvoiceProvider.PAYRAM:
            # Never reuse an invoice from a retired provider: its reference
            # would make the new sale look like a duplicate.
            raise ConflictError("This invoice uses a retired payment provider; start a new order.")
        if invoice.status in _PAID_STATUSES:
            return invoice
        if invoice.status not in _EXPIRABLE_STATUSES:
            raise ConflictError("This invoice can no longer be paid.")
        if invoice.currency.upper() != "USD":
            raise ConfigurationError("Gumroad charges USD invoices only.")
        if invoice.checkout_url and _not_expired(invoice):
            return invoice
        if not user_email:
            raise ValidationError("An email address is required for the payment receipt.")

        invoice = await self._ensure_correlation_token(invoice)
        hours = max(1, _as_int(await self._setting(KEY_CHECKOUT_EXPIRY_HOURS, 24)))
        expires_at = datetime.now(UTC) + timedelta(hours=hours)
        try:
            session = await provider.create_checkout(
                CheckoutRequest(
                    invoice_reference=invoice.reference,
                    customer_email=user_email,
                    amount_usd=Decimal(str(invoice.amount)),
                    currency="USD",
                    correlation_token=invoice.correlation_token or "",
                )
            )
        except UpstreamError as exc:
            await self._invoices.update(
                invoice.id, {"failure_reason": "The payment provider could not create a checkout."}
            )
            emit(BILLING_CHECKOUT_CREATED, invoice_id=invoice.id, ok=False)
            raise exc

        metadata = _merge_metadata(invoice.metadata, {"customer_email": user_email})
        invoice = await self._invoices.update(
            invoice.id,
            {
                "provider": InvoiceProvider.GUMROAD.value,
                "checkout_url": session.url,
                "status": InvoiceStatus.AWAITING_PAYMENT.value,
                "expires_at": expires_at.isoformat(),
                "failure_reason": None,
                "metadata": metadata,
            },
        )
        emit(
            BILLING_CHECKOUT_CREATED,
            invoice_id=invoice.id,
            provider=provider.name,
            ok=True,
        )
        return invoice

    # -- reconciliation ------------------------------------------------------
    async def reconcile(self, invoice: BillingInvoice) -> BillingInvoice:
        provider = self._provider
        if provider is None or invoice.provider == InvoiceProvider.PAYRAM:
            # Historical PayRam rows are kept read-only; Gumroad cannot read
            # them and they must not be reinterpreted.
            return invoice
        if invoice.status in _PAID_STATUSES and invoice.fulfilled_at is not None:
            return invoice

        payment: ProviderPayment | None = None
        if invoice.provider_reference:
            payment = await provider.fetch_payment(invoice.provider_reference)
            if payment.reference != invoice.provider_reference:
                logger.warning(
                    "gumroad_reconcile_reference_mismatch",
                    invoice_id=invoice.id,
                    expected=invoice.provider_reference,
                )
                return invoice
        elif invoice.correlation_token:
            email = _metadata_text(invoice.metadata, "customer_email")
            if email:
                payment = await provider.find_payment(invoice.correlation_token, email)
        if payment is None:
            return invoice

        await self._apply_sale(invoice, payment)
        emit(BILLING_RECONCILED, invoice_id=invoice.id, state=payment.state.value)
        return await self._reload(invoice.id)

    # -- webhook -------------------------------------------------------------
    async def handle_webhook(
        self,
        raw_body: bytes,
        headers: dict[str, str],
        *,
        callback_secret: str | None,
    ) -> None:
        provider = self._require_provider()
        notification = provider.verify_webhook(raw_body, headers, callback_secret)

        existing = await self._events.get_by_key(notification.event_key)
        if existing is not None and existing.processed:
            return
        invoice = await self._resolve_invoice(notification)

        event = existing
        if event is None:
            try:
                event = await self._events.create(
                    {
                        "provider": provider.name,
                        "event_key": notification.event_key,
                        "invoice": invoice.id if invoice is not None else None,
                        "event_type": notification.kind.value,
                        "provider_reference": notification.sale_id or notification.subscription_id,
                        "status": notification.kind.value,
                        "payload": _sanitized_notification(notification),
                        "processed": False,
                    }
                )
            except ConflictError, ValidationError:
                # A concurrent delivery won the unique index; reuse its record.
                event = await self._events.get_by_key(notification.event_key)
                if event is None:
                    raise
                if event.processed:
                    return

        if invoice is None:
            logger.warning(
                "gumroad_webhook_unknown_invoice",
                event_key=notification.event_key,
                sale_id=notification.sale_id,
                subscription_id=notification.subscription_id,
            )
            await self._mark_processed(event.id)
            return

        try:
            # Re-read: a concurrent delivery may have changed the invoice.
            fresh = await self._invoices.get(invoice.id)
            if notification.kind in _SALE_EVENTS:
                if not notification.sale_id:
                    raise ValidationError("The Gumroad notification has no sale id.")
                payment = await provider.fetch_payment(notification.sale_id)
                if notification.kind == ProviderEventKind.REFUND and notification.refunded:
                    payment = replace(payment, refunded=True, state=ProviderState.REFUNDED)
                await self._apply_sale(fresh, payment, test_hint=notification.test)
            else:
                if not notification.subscription_id:
                    raise ValidationError("The Gumroad notification has no subscription id.")
                subscription = await provider.fetch_subscription(notification.subscription_id)
                await self._apply_subscription(fresh, subscription, notification.kind)
        except Exception as exc:
            await self._events.update(event.id, {"processed": False, "error": type(exc).__name__})
            emit(BILLING_FULFILLMENT_FAILED, invoice_id=invoice.id, error=type(exc).__name__)
            raise
        await self._mark_processed(event.id)

    # -- sale state ----------------------------------------------------------
    async def _apply_sale(
        self,
        invoice: BillingInvoice,
        payment: ProviderPayment,
        *,
        test_hint: bool = False,
    ) -> None:
        provider = self._require_provider()
        if (payment.test or test_hint) and not provider.allow_test_sales:
            await self._flag_review(invoice, "A Gumroad test sale was ignored.")
            return
        if not provider.product_id or payment.product_id != provider.product_id:
            await self._flag_review(
                invoice, "The Gumroad product does not match the configured product."
            )
            return
        if invoice.provider_reference and invoice.provider_reference != payment.reference:
            # A renewal sale may not repeat the original custom fields, so the
            # subscription id (not the checkout token) is its identity.
            renewal = payment.recurring or (
                payment.subscription_id is not None
                and payment.subscription_id == invoice.provider_subscription_id
            )
            if renewal:
                await self._record_renewal(invoice, payment)
                return
            await self._flag_review(
                invoice, "A second Gumroad sale matched an invoice that is already paid."
            )
            return

        # The token binds a *new* sale to this invoice. Once the sale id is
        # stored, identity is already proven and later refund/dispute reads of
        # the same sale do not need the custom field again.
        if (
            invoice.provider_reference is None
            and invoice.correlation_token
            and (
                not payment.invoice_reference
                or not hmac.compare_digest(payment.invoice_reference, invoice.correlation_token)
            )
        ):
            await self._flag_review(
                invoice,
                "The Gumroad sale does not carry this invoice's checkout reference.",
            )
            return

        expected = Decimal(str(invoice.amount))
        paid = payment.filled_amount_usd
        if paid is None:
            await self._flag_review(invoice, "Gumroad did not report the amount paid.")
            return
        if paid + _AMOUNT_TOLERANCE < expected:
            await self._flag_review(invoice, "The amount paid is less than the invoice.")
            return

        if payment.refunded or payment.chargedback:
            await self._record_refund(invoice, payment)
            return
        if payment.partially_refunded:
            await self._record_partial_refund(invoice, payment)
            return
        if payment.disputed and not payment.dispute_won:
            await self._record_dispute(invoice, payment, won=False)
            return
        if payment.dispute_won:
            invoice = await self._record_dispute(invoice, payment, won=True)

        already_paid = invoice.status in _PAID_STATUSES
        metadata = _merge_metadata(invoice.metadata, {"sale": _sale_snapshot(payment)})
        if payment.purchaser_email:
            metadata["customer_email"] = payment.purchaser_email
        invoice = await self._invoices.update(
            invoice.id,
            {
                "status": InvoiceStatus.PAID.value,
                "provider": InvoiceProvider.GUMROAD.value,
                "provider_reference": invoice.provider_reference or payment.reference,
                "provider_subscription_id": payment.subscription_id
                or invoice.provider_subscription_id,
                "paid_amount": float(paid),
                "paid_currency": "USD",
                "paid_at": (invoice.paid_at or datetime.now(UTC)).isoformat(),
                "failure_reason": None,
                "metadata": metadata,
            },
        )
        emit(
            BILLING_PAYMENT_RECEIVED,
            invoice_id=invoice.id,
            provider_reference=payment.reference,
            state=payment.state.value,
            duplicate=already_paid,
        )
        await self.fulfill(invoice)

    async def _record_renewal(self, invoice: BillingInvoice, payment: ProviderPayment) -> None:
        metadata = _merge_metadata(invoice.metadata, {})
        renewals = metadata.get("renewals")
        renewals = list(renewals) if isinstance(renewals, list) else []
        if any(
            item.get("sale_id") == payment.reference for item in renewals if isinstance(item, dict)
        ):
            return
        renewals.append(_sale_snapshot(payment))
        metadata["renewals"] = renewals[-_MAX_RENEWALS:]
        await self._invoices.update(
            invoice.id,
            {
                "provider_subscription_id": payment.subscription_id
                or invoice.provider_subscription_id,
                "metadata": metadata,
            },
        )
        emit(
            BILLING_PAYMENT_RECEIVED,
            invoice_id=invoice.id,
            provider_reference=payment.reference,
            state="renewal",
            duplicate=True,
        )

    async def _record_refund(self, invoice: BillingInvoice, payment: ProviderPayment) -> None:
        reason = (
            "The payment was charged back." if payment.chargedback else "The payment was refunded."
        )
        metadata = _merge_metadata(invoice.metadata, {"refund": _sale_snapshot(payment)})
        # A refund is a compensating state: the original amount, paid_at and
        # fulfilled_at stay intact. Work already delivered is not revoked.
        await self._invoices.update(
            invoice.id,
            {
                "status": InvoiceStatus.REFUNDED.value,
                "refunded_at": datetime.now(UTC).isoformat(),
                "failure_reason": reason,
                "metadata": metadata,
            },
        )
        emit(BILLING_REFUNDED, invoice_id=invoice.id, chargeback=payment.chargedback)

    async def _record_partial_refund(
        self, invoice: BillingInvoice, payment: ProviderPayment
    ) -> None:
        metadata = _merge_metadata(invoice.metadata, {"partial_refund": _sale_snapshot(payment)})
        await self._invoices.update(
            invoice.id,
            {
                "failure_reason": "Part of the payment was refunded; review manually.",
                "metadata": metadata,
            },
        )

    async def _record_dispute(
        self, invoice: BillingInvoice, payment: ProviderPayment, *, won: bool
    ) -> BillingInvoice:
        metadata = _merge_metadata(
            invoice.metadata, {"dispute": {"won": won, "sale": _sale_snapshot(payment)}}
        )
        if won:
            update: dict[str, Any] = {"metadata": metadata}
            if invoice.failure_reason and invoice.failure_reason.startswith("Payment is disputed"):
                update["failure_reason"] = None
            updated = await self._invoices.update(invoice.id, update)
            emit(BILLING_DISPUTED, invoice_id=invoice.id, won=True)
            return updated

        # A dispute is not a final chargeback: keep a paid entitlement in place
        # until the dispute is resolved. An unpaid invoice goes to review.
        if invoice.status in _PAID_STATUSES:
            await self._invoices.update(
                invoice.id,
                {
                    "failure_reason": "Payment is disputed; access is retained pending resolution.",
                    "metadata": metadata,
                },
            )
        else:
            await self._invoices.update(
                invoice.id,
                {
                    "status": InvoiceStatus.REVIEW.value,
                    "failure_reason": "Payment is disputed; awaiting resolution.",
                    "metadata": metadata,
                },
            )
        emit(BILLING_DISPUTED, invoice_id=invoice.id, won=False)
        return invoice

    # -- subscription state --------------------------------------------------
    async def _apply_subscription(
        self,
        invoice: BillingInvoice,
        subscription: ProviderSubscription,
        kind: ProviderEventKind,
    ) -> None:
        provider = self._require_provider()
        if provider.product_id and subscription.product_id != provider.product_id:
            logger.warning(
                "gumroad_subscription_product_mismatch",
                invoice_id=invoice.id,
                expected=provider.product_id,
            )
            return

        metadata = _merge_metadata(
            invoice.metadata, {"subscription": _subscription_snapshot(subscription, kind)}
        )
        update: dict[str, Any] = {"metadata": metadata}
        if invoice.provider_subscription_id is None:
            update["provider_subscription_id"] = subscription.reference

        if kind == ProviderEventKind.SUBSCRIPTION_ENDED and invoice.status in _OPEN_STATUSES:
            # Nothing was delivered from this invoice; stop waiting for payment.
            update["status"] = InvoiceStatus.CANCELLED.value
            update["failure_reason"] = (
                "The Gumroad subscription ended before payment was confirmed."
            )
        # Cancellation, downgrade, and end never revoke an already-paid book.
        # The paid period runs to its end; a delivered translation is final.

        await self._invoices.update(invoice.id, update)

    # -- fulfillment ---------------------------------------------------------
    async def fulfill(self, invoice: BillingInvoice) -> BillingInvoice:
        """Queue the paid job exactly once; safe to call repeatedly."""
        # Re-read before touching the job: a concurrent webhook/reconcile may
        # already have fulfilled this invoice.
        # ponytail: read-then-write; PocketBase has no conditional update. The
        # event dedupe makes a true double-fulfill rare; add a single-flight
        # lock if duplicate queuing is ever observed.
        current = await self._invoices.get(invoice.id)
        if current.fulfilled_at is not None:
            return current
        if current.job is None:
            return await self._invoices.update(current.id, {"status": InvoiceStatus.REVIEW.value})
        try:
            job = await self._jobs.get(current.job)
        except Exception:
            emit(BILLING_FULFILLMENT_FAILED, invoice_id=current.id, error="job_read_failed")
            raise
        if job.status == "awaiting_payment":
            await self._jobs.update(job.id, {"status": "queued"})
        elif job.status in ("cancelled", "failed"):
            return await self._invoices.update(
                current.id,
                {
                    "status": InvoiceStatus.REVIEW.value,
                    "failure_reason": "The translation job is no longer runnable.",
                },
            )
        fulfilled = await self._invoices.update(
            current.id,
            {
                "status": InvoiceStatus.PAID.value,
                "fulfilled_at": (current.fulfilled_at or datetime.now(UTC)).isoformat(),
            },
        )
        emit(BILLING_FULFILLED, invoice_id=current.id, job_id=job.id)
        return fulfilled

    # -- internals -----------------------------------------------------------
    async def _grant_free(self, invoice: BillingInvoice, job: TranslationJob) -> BillingInvoice:
        invoice = await self._invoices.update(
            invoice.id,
            {
                "status": InvoiceStatus.PAID.value,
                "provider": InvoiceProvider.FREE.value,
                "paid_amount": 0.0,
                "paid_currency": invoice.currency,
                "paid_at": datetime.now(UTC).isoformat(),
            },
        )
        await self._jobs.update(job.id, {"status": "queued"})
        invoice = await self._invoices.update(
            invoice.id,
            {"fulfilled_at": datetime.now(UTC).isoformat()},
        )
        emit(BILLING_FULFILLED, invoice_id=invoice.id, job_id=job.id, free=True)
        return invoice

    async def _attach_to_job(self, job: TranslationJob, invoice: BillingInvoice) -> None:
        metadata = dict(job.metadata or {})
        order = dict(metadata.get("order") or {}) if isinstance(metadata.get("order"), dict) else {}
        order["invoice_id"] = invoice.id
        order["invoice_reference"] = invoice.reference
        metadata["order"] = order
        await self._jobs.update(job.id, {"metadata": metadata})

    async def _flag_review(self, invoice: BillingInvoice, reason: str) -> None:
        if invoice.status in _PAID_STATUSES:
            # Never downgrade a paid book because a later event looked wrong.
            metadata = _merge_metadata(invoice.metadata, {"review": reason})
            await self._invoices.update(
                invoice.id, {"failure_reason": reason, "metadata": metadata}
            )
            logger.warning("gumroad_payment_review", invoice_id=invoice.id, reason=reason)
            return
        await self._invoices.update(
            invoice.id,
            {"status": InvoiceStatus.REVIEW.value, "failure_reason": reason},
        )
        logger.warning("gumroad_payment_review", invoice_id=invoice.id, reason=reason)

    async def _resolve_invoice(self, notification: ProviderNotification) -> BillingInvoice | None:
        if notification.invoice_reference:
            invoice = await self._invoices.get_by_correlation_token(notification.invoice_reference)
            if invoice is not None:
                return invoice
        if notification.sale_id:
            invoice = await self._invoices.get_by_provider_reference(notification.sale_id)
            if invoice is not None:
                return invoice
        if notification.subscription_id:
            return await self._invoices.get_by_provider_subscription_id(
                notification.subscription_id
            )
        return None

    async def _ensure_correlation_token(self, invoice: BillingInvoice) -> BillingInvoice:
        if invoice.correlation_token:
            return invoice
        return await self._invoices.update(
            invoice.id, {"correlation_token": secrets.token_urlsafe(32)}
        )

    async def _mark_processed(self, event_id: str) -> None:
        await self._events.update(
            event_id,
            {"processed": True, "processed_at": datetime.now(UTC).isoformat(), "error": None},
        )

    async def _reload(self, invoice_id: str) -> BillingInvoice:
        return await self._invoices.get(invoice_id)

    async def _setting(self, key: str, default: Any) -> Any:
        return await self._settings.get(key, default)

    def _require_provider(self) -> PaymentProvider:
        if not self._enabled or self._provider is None:
            raise ConfigurationError(
                "Billing is not enabled. Configure BILLING_ENABLED and the Gumroad "
                "credentials first."
            )
        return self._provider


def _invoice_reference() -> str:
    return f"BF-{uuid.uuid4().hex[:12].upper()}"


def _sanitized_notification(notification: ProviderNotification) -> dict[str, Any]:
    """Keep only fields needed to audit a delivery, never full payloads."""
    return {
        "event": notification.kind.value,
        "sale_id": notification.sale_id,
        "subscription_id": notification.subscription_id,
        "product_id": notification.product_id,
        "test": notification.test,
    }


def _sale_snapshot(payment: ProviderPayment) -> dict[str, Any]:
    return {
        "sale_id": payment.reference,
        "product_id": payment.product_id,
        "state": payment.state.value,
        "price_cents": _cents(payment.filled_amount_usd),
        "currency": payment.currency,
        "subscription_id": payment.subscription_id,
        "recurring": payment.recurring,
        "refunded": payment.refunded,
        "partially_refunded": payment.partially_refunded,
        "chargedback": payment.chargedback,
        "disputed": payment.disputed,
        "dispute_won": payment.dispute_won,
        "cancelled": payment.cancelled,
        "ended": payment.ended,
        "timestamp": payment.timestamp,
    }


def _subscription_snapshot(
    subscription: ProviderSubscription, kind: ProviderEventKind
) -> dict[str, Any]:
    return {
        "subscription_id": subscription.reference,
        "product_id": subscription.product_id,
        "state": subscription.state.value,
        "recurrence": subscription.recurrence,
        "cancelled_at": _iso(subscription.cancelled_at),
        "ended_at": _iso(subscription.ended_at),
        "failed_at": _iso(subscription.failed_at),
        "user_requested_cancellation_at": _iso(subscription.user_requested_cancellation_at),
        "last_event": kind.value,
    }


def _merge_metadata(metadata: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = dict(metadata)
    merged.update(updates)
    return merged


def _metadata_text(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    return str(value) if value not in (None, "") else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _cents(value: Decimal | None) -> int | None:
    return int(value * 100) if value is not None else None


def _as_decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except ArithmeticError, ValueError:
        return None


def _as_int(value: object) -> int:
    try:
        return int(str(value)) if value not in (None, "") else 0
    except TypeError, ValueError:
        return 0


def _not_expired(invoice: BillingInvoice) -> bool:
    if invoice.expires_at is None:
        return True
    expires = invoice.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    return expires > datetime.now(UTC)
