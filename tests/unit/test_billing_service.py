"""Billing service: allowance, checkout, sales, refunds, disputes, subscriptions.

The provider is faked at its normalized boundary; Gumroad's wire format is
covered in ``test_gumroad_provider``. PocketBase is the in-memory fake.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from app.api.repositories import build_repositories
from app.billing.payments.base import (
    CheckoutRequest,
    CheckoutSession,
    InvalidWebhookError,
    ProviderEventKind,
    ProviderNotification,
    ProviderPayment,
    ProviderState,
    ProviderSubscription,
    SubscriptionState,
)
from app.billing.service import BillingService
from app.exceptions import ConflictError, UpstreamError, ValidationError
from app.repositories.pocketbase import PocketBaseClient
from app.settings.service import SettingsService

SECRET = "local-callback-secret"


class FakeProvider:
    name = "gumroad"
    product_id = "prod-1"
    allow_test_sales = False

    def __init__(self) -> None:
        self.notification: ProviderNotification | None = None
        self.payment: ProviderPayment | None = None
        self.found: ProviderPayment | None = None
        self.subscription: ProviderSubscription | None = None
        self.checkout_requests: list[CheckoutRequest] = []

    async def create_checkout(self, request: CheckoutRequest) -> CheckoutSession:
        self.checkout_requests.append(request)
        return CheckoutSession(url="https://gumroad.com/l/book?wanted=true")

    async def fetch_payment(self, reference: str) -> ProviderPayment:
        assert self.payment is not None
        return self.payment

    async def find_payment(
        self, correlation_token: str, customer_email: str
    ) -> ProviderPayment | None:
        return self.found

    async def fetch_subscription(self, reference: str) -> ProviderSubscription:
        assert self.subscription is not None
        return self.subscription

    def verify_webhook(
        self,
        raw_body: bytes,
        headers: Mapping[str, str],
        callback_secret: str | None,
    ) -> ProviderNotification:
        if callback_secret != SECRET:
            raise InvalidWebhookError()
        assert self.notification is not None
        return self.notification

    def is_checkout_url_allowed(self, url: str) -> bool:
        return url.startswith("https://gumroad.com/")


def _repos(pb: PocketBaseClient) -> Any:
    return build_repositories(pb, token=None)


def _seed_settings(fake_pb: Any, free_books: int = 0) -> None:
    fake_pb.seed(
        "system_settings",
        {"key": "billing.free_managed_books", "type": "int", "value": free_books},
    )
    fake_pb.seed(
        "system_settings", {"key": "billing.default_currency", "type": "string", "value": "USD"}
    )
    fake_pb.seed(
        "system_settings", {"key": "billing.book_price_usd", "type": "float", "value": 7.0}
    )


def _seed_job(fake_pb: Any, *, job_id: str = "job1", amount: float = 7.0) -> dict[str, Any]:
    return fake_pb.seed(
        "translation_jobs",
        {
            "id": job_id,
            "workspace": "ws1",
            "document": "doc1",
            "source_language": "en",
            "target_language": "fa",
            "status": "awaiting_payment",
            "metadata": {
                "order": {
                    "billing_mode": "managed",
                    "pages": 10,
                    "blocks": 1,
                    "amount": amount,
                    "currency": "USD",
                }
            },
        },
    )


def _service(
    pb: PocketBaseClient,
    provider: FakeProvider | None = None,
    *,
    enabled: bool = True,
) -> BillingService:
    repos = _repos(pb)
    return BillingService(
        invoices=repos.invoices,
        events=repos.billing_events,
        claims=repos.billing_claims,
        jobs=repos.jobs,
        settings=SettingsService(repos.settings),
        provider=provider or FakeProvider(),
        billing_enabled=enabled,
    )


def _payment(
    *,
    reference: str = "sale-1",
    token: str | None,
    product_id: str = "prod-1",
    state: ProviderState = ProviderState.PAID,
    paid: str = "7.00",
    **overrides: Any,
) -> ProviderPayment:
    return ProviderPayment(
        reference=reference,
        invoice_reference=token,
        state=state,
        product_id=product_id,
        filled_amount_usd=Decimal(paid) if paid is not None else None,
        currency="USD",
        purchaser_email="reader@example.com",
        timestamp=1_700_000_000,
        **overrides,
    )


def _notification(
    kind: ProviderEventKind = ProviderEventKind.SALE,
    *,
    token: str | None,
    sale_id: str | None = "sale-1",
    subscription_id: str | None = None,
    test: bool = False,
    refunded: bool = False,
) -> ProviderNotification:
    return ProviderNotification(
        kind=kind,
        event_key=f"{kind.value}:{sale_id or subscription_id}",
        sale_id=sale_id,
        subscription_id=subscription_id,
        product_id="prod-1",
        invoice_reference=token,
        test=test,
        refunded=refunded,
    )


async def _start(pb: PocketBaseClient, service: BillingService, job_id: str = "job1") -> Any:
    job = await _repos(pb).jobs.get(job_id)
    return await service.start(job=job, workspace_id="ws1", user_id="user1")


async def _paid_invoice(
    fake_pb: Any, pb: PocketBaseClient, provider: FakeProvider
) -> tuple[BillingService, Any]:
    _seed_settings(fake_pb)
    _seed_job(fake_pb)
    service = _service(pb, provider)
    invoice = await _start(pb, service)
    provider.notification = _notification(token=invoice.correlation_token)
    provider.payment = _payment(token=invoice.correlation_token)
    await service.handle_webhook(b"", {}, callback_secret=SECRET)
    return service, await _repos(pb).invoices.get(invoice.id)


async def _job_status(pb: PocketBaseClient, job_id: str = "job1") -> str:
    return str((await _repos(pb).jobs.get(job_id)).status)


async def test_requires_payment_only_for_managed_when_enabled(
    fake_pb: Any, pb: PocketBaseClient
) -> None:
    enabled = _service(pb)
    assert enabled.requires_payment("managed") is True
    assert enabled.requires_payment("own_api") is False

    disabled = _service(pb, enabled=False)
    assert disabled.requires_payment("managed") is False


async def test_free_allowance_queues_job_and_marks_invoice_paid(
    fake_pb: Any, pb: PocketBaseClient
) -> None:
    _seed_settings(fake_pb, free_books=1)
    _seed_job(fake_pb)
    service = _service(pb)

    invoice = await _start(pb, service)

    assert invoice is not None
    assert invoice.status == "paid"
    assert invoice.provider == "free"
    assert invoice.fulfilled_at is not None
    assert await _job_status(pb) == "queued"
    assert len(fake_pb.collections["billing_free_claims"]) == 1


async def test_second_book_gets_a_payable_invoice_when_allowance_is_used(
    fake_pb: Any, pb: PocketBaseClient
) -> None:
    _seed_settings(fake_pb, free_books=1)
    _seed_job(fake_pb, job_id="job1")
    _seed_job(fake_pb, job_id="job2")
    service = _service(pb)

    first = await _start(pb, service, "job1")
    second = await _start(pb, service, "job2")

    assert first is not None and first.status == "paid"
    assert second is not None and second.status == "pending"
    assert second.provider == "none"
    assert second.correlation_token is not None
    assert await _job_status(pb, "job2") == "awaiting_payment"
    assert len(fake_pb.collections["billing_free_claims"]) == 1


async def test_zero_allowance_never_claims(fake_pb: Any, pb: PocketBaseClient) -> None:
    _seed_settings(fake_pb, free_books=0)
    _seed_job(fake_pb)
    service = _service(pb)

    invoice = await _start(pb, service)

    assert invoice is not None and invoice.status == "pending"
    assert "billing_free_claims" not in fake_pb.collections
    assert await _job_status(pb) == "awaiting_payment"


async def test_checkout_creates_a_gumroad_url_with_the_correlation_token(
    fake_pb: Any, pb: PocketBaseClient
) -> None:
    _seed_settings(fake_pb)
    _seed_job(fake_pb)
    provider = FakeProvider()
    service = _service(pb, provider)
    invoice = await _start(pb, service)
    assert invoice is not None

    paid = await service.create_checkout(invoice, user_email="reader@example.com")

    assert paid.status == "awaiting_payment"
    assert paid.provider == "gumroad"
    assert paid.checkout_url == "https://gumroad.com/l/book?wanted=true"
    request = provider.checkout_requests[-1]
    assert request.correlation_token == invoice.correlation_token
    assert request.amount_usd == Decimal("7.0")
    assert request.customer_email == "reader@example.com"

    # A live hosted checkout is reused rather than recreated.
    again = await service.create_checkout(paid, user_email="reader@example.com")
    assert again.checkout_url == paid.checkout_url
    assert len(provider.checkout_requests) == 1


async def test_checkout_requires_an_email(fake_pb: Any, pb: PocketBaseClient) -> None:
    _seed_settings(fake_pb)
    _seed_job(fake_pb)
    service = _service(pb)
    invoice = await _start(pb, service)
    assert invoice is not None

    with pytest.raises(ValidationError, match="email address is required"):
        await service.create_checkout(invoice, user_email=None)


async def test_verified_sale_marks_paid_queues_once_and_is_idempotent(
    fake_pb: Any, pb: PocketBaseClient
) -> None:
    provider = FakeProvider()
    service, invoice = await _paid_invoice(fake_pb, pb, provider)
    assert invoice.status == "paid"
    assert invoice.fulfilled_at is not None
    assert invoice.paid_amount == 7.0
    assert invoice.provider_reference == "sale-1"
    assert await _job_status(pb) == "queued"

    await service.handle_webhook(b"", {}, callback_secret=SECRET)
    stored = await _repos(pb).invoices.get(invoice.id)
    assert stored.status == "paid"
    assert len(fake_pb.collections["billing_events"]) == 1


async def test_short_payment_goes_to_review_and_never_queues(
    fake_pb: Any, pb: PocketBaseClient
) -> None:
    _seed_settings(fake_pb)
    _seed_job(fake_pb)
    provider = FakeProvider()
    service = _service(pb, provider)
    invoice = await _start(pb, service)
    assert invoice is not None

    provider.notification = _notification(token=invoice.correlation_token)
    provider.payment = _payment(token=invoice.correlation_token, paid="5.00")
    await service.handle_webhook(b"", {}, callback_secret=SECRET)

    stored = await _repos(pb).invoices.get(invoice.id)
    assert stored.status == "review"
    assert stored.failure_reason is not None
    assert await _job_status(pb) == "awaiting_payment"


async def test_overpayment_pays_the_book_without_extra_entitlement(
    fake_pb: Any, pb: PocketBaseClient
) -> None:
    _seed_settings(fake_pb)
    _seed_job(fake_pb)
    provider = FakeProvider()
    service = _service(pb, provider)
    invoice = await _start(pb, service)
    assert invoice is not None

    provider.notification = _notification(token=invoice.correlation_token)
    provider.payment = _payment(token=invoice.correlation_token, paid="9.00")
    await service.handle_webhook(b"", {}, callback_secret=SECRET)

    stored = await _repos(pb).invoices.get(invoice.id)
    assert stored.status == "paid"
    assert stored.paid_amount == 9.0
    assert await _job_status(pb) == "queued"


async def test_wrong_product_goes_to_review(fake_pb: Any, pb: PocketBaseClient) -> None:
    _seed_settings(fake_pb)
    _seed_job(fake_pb)
    provider = FakeProvider()
    service = _service(pb, provider)
    invoice = await _start(pb, service)
    assert invoice is not None

    provider.notification = _notification(token=invoice.correlation_token)
    provider.payment = _payment(token=invoice.correlation_token, product_id="other")
    await service.handle_webhook(b"", {}, callback_secret=SECRET)

    stored = await _repos(pb).invoices.get(invoice.id)
    assert stored.status == "review"
    assert await _job_status(pb) == "awaiting_payment"


async def test_sale_without_the_invoice_token_goes_to_review(
    fake_pb: Any, pb: PocketBaseClient
) -> None:
    _seed_settings(fake_pb)
    _seed_job(fake_pb)
    provider = FakeProvider()
    service = _service(pb, provider)
    invoice = await _start(pb, service)
    assert invoice is not None

    provider.notification = _notification(token=invoice.correlation_token)
    provider.payment = _payment(token=None)
    await service.handle_webhook(b"", {}, callback_secret=SECRET)

    stored = await _repos(pb).invoices.get(invoice.id)
    assert stored.status == "review"
    assert await _job_status(pb) == "awaiting_payment"


async def test_test_sale_is_ignored(fake_pb: Any, pb: PocketBaseClient) -> None:
    _seed_settings(fake_pb)
    _seed_job(fake_pb)
    provider = FakeProvider()
    service = _service(pb, provider)
    invoice = await _start(pb, service)
    assert invoice is not None

    provider.notification = _notification(token=invoice.correlation_token, test=True)
    provider.payment = _payment(token=invoice.correlation_token)
    await service.handle_webhook(b"", {}, callback_secret=SECRET)

    stored = await _repos(pb).invoices.get(invoice.id)
    assert stored.status == "review"
    assert await _job_status(pb) == "awaiting_payment"


async def test_second_distinct_sale_for_a_paid_invoice_goes_to_review(
    fake_pb: Any, pb: PocketBaseClient
) -> None:
    provider = FakeProvider()
    service, invoice = await _paid_invoice(fake_pb, pb, provider)

    provider.notification = _notification(token=invoice.correlation_token, sale_id="sale-2")
    provider.payment = _payment(reference="sale-2", token=invoice.correlation_token)
    await service.handle_webhook(b"", {}, callback_secret=SECRET)

    stored = await _repos(pb).invoices.get(invoice.id)
    assert stored.status == "paid"
    assert stored.failure_reason is not None
    assert await _job_status(pb) == "queued"
    assert not fake_pb.collections.get("billing_free_claims")


async def test_renewal_is_recorded_once_and_never_regrants(
    fake_pb: Any, pb: PocketBaseClient
) -> None:
    provider = FakeProvider()
    service, invoice = await _paid_invoice(fake_pb, pb, provider)
    invoice = await _repos(pb).invoices.update(invoice.id, {"provider_subscription_id": "sub-1"})

    # Renewals may not repeat the original custom fields; the subscription id
    # is their identity.
    provider.notification = _notification(
        token=None, sale_id="sale-renewal", subscription_id="sub-1"
    )
    provider.payment = _payment(
        reference="sale-renewal", token=None, subscription_id="sub-1", recurring=True
    )
    await service.handle_webhook(b"", {}, callback_secret=SECRET)

    stored = await _repos(pb).invoices.get(invoice.id)
    assert stored.status == "paid"
    assert stored.fulfilled_at is not None
    renewals = stored.metadata["renewals"]
    assert [item["sale_id"] for item in renewals] == ["sale-renewal"]

    # Reconcile re-reads the same renewal; the snapshot is not appended twice.
    await service.reconcile(stored)
    stored = await _repos(pb).invoices.get(invoice.id)
    assert [item["sale_id"] for item in stored.metadata["renewals"]] == ["sale-renewal"]


async def test_refund_keeps_the_delivered_book(fake_pb: Any, pb: PocketBaseClient) -> None:
    provider = FakeProvider()
    service, invoice = await _paid_invoice(fake_pb, pb, provider)
    assert invoice.fulfilled_at is not None

    # A refund read may omit the custom field; the stored sale id is enough.
    provider.notification = _notification(
        ProviderEventKind.REFUND, token=invoice.correlation_token, refunded=True
    )
    provider.payment = _payment(token=None)
    await service.handle_webhook(b"", {}, callback_secret=SECRET)

    stored = await _repos(pb).invoices.get(invoice.id)
    assert stored.status == "refunded"
    assert stored.refunded_at is not None
    assert stored.paid_amount == 7.0
    assert stored.fulfilled_at is not None
    assert await _job_status(pb) == "queued"


async def test_chargeback_is_recorded_as_a_refund(fake_pb: Any, pb: PocketBaseClient) -> None:
    provider = FakeProvider()
    service, invoice = await _paid_invoice(fake_pb, pb, provider)

    provider.notification = _notification(
        ProviderEventKind.REFUND, token=invoice.correlation_token, refunded=True
    )
    provider.payment = _payment(token=invoice.correlation_token, chargedback=True)
    await service.handle_webhook(b"", {}, callback_secret=SECRET)

    stored = await _repos(pb).invoices.get(invoice.id)
    assert stored.status == "refunded"
    assert "charged back" in (stored.failure_reason or "")


async def test_partial_refund_keeps_paid_and_flags_review(
    fake_pb: Any, pb: PocketBaseClient
) -> None:
    provider = FakeProvider()
    service, invoice = await _paid_invoice(fake_pb, pb, provider)

    provider.notification = _notification(ProviderEventKind.REFUND, token=invoice.correlation_token)
    provider.payment = _payment(token=invoice.correlation_token, partially_refunded=True)
    await service.handle_webhook(b"", {}, callback_secret=SECRET)

    stored = await _repos(pb).invoices.get(invoice.id)
    assert stored.status == "paid"
    assert "Part of the payment was refunded" in (stored.failure_reason or "")


async def test_dispute_does_not_revoke_access_until_resolved(
    fake_pb: Any, pb: PocketBaseClient
) -> None:
    provider = FakeProvider()
    service, invoice = await _paid_invoice(fake_pb, pb, provider)

    provider.notification = _notification(
        ProviderEventKind.DISPUTE, token=invoice.correlation_token
    )
    provider.payment = _payment(token=invoice.correlation_token, disputed=True)
    await service.handle_webhook(b"", {}, callback_secret=SECRET)

    stored = await _repos(pb).invoices.get(invoice.id)
    assert stored.status == "paid"
    assert stored.fulfilled_at is not None
    assert "disputed" in (stored.failure_reason or "")

    provider.notification = _notification(
        ProviderEventKind.DISPUTE_WON, token=invoice.correlation_token
    )
    provider.payment = _payment(token=invoice.correlation_token, disputed=True, dispute_won=True)
    await service.handle_webhook(b"", {}, callback_secret=SECRET)

    stored = await _repos(pb).invoices.get(invoice.id)
    assert stored.status == "paid"
    assert stored.failure_reason is None


async def test_cancellation_does_not_revoke_a_paid_book(fake_pb: Any, pb: PocketBaseClient) -> None:
    provider = FakeProvider()
    service, invoice = await _paid_invoice(fake_pb, pb, provider)

    provider.notification = _notification(
        ProviderEventKind.CANCELLATION,
        token=invoice.correlation_token,
        sale_id=None,
        subscription_id="sub-1",
    )
    provider.subscription = ProviderSubscription(
        reference="sub-1",
        state=SubscriptionState.PENDING_CANCELLATION,
        product_id="prod-1",
        cancelled_at=datetime(2026, 12, 1, tzinfo=UTC),
    )
    await service.handle_webhook(b"", {}, callback_secret=SECRET)

    stored = await _repos(pb).invoices.get(invoice.id)
    assert stored.status == "paid"
    assert stored.fulfilled_at is not None
    assert await _job_status(pb) == "queued"


async def test_subscription_ending_cancels_an_unpaid_invoice(
    fake_pb: Any, pb: PocketBaseClient
) -> None:
    _seed_settings(fake_pb)
    _seed_job(fake_pb)
    provider = FakeProvider()
    service = _service(pb, provider)
    invoice = await _start(pb, service)
    assert invoice is not None
    invoice = await _repos(pb).invoices.update(invoice.id, {"provider_subscription_id": "sub-1"})

    provider.notification = _notification(
        ProviderEventKind.SUBSCRIPTION_ENDED,
        token=invoice.correlation_token,
        sale_id=None,
        subscription_id="sub-1",
    )
    provider.subscription = ProviderSubscription(
        reference="sub-1",
        state=SubscriptionState.ENDED,
        product_id="prod-1",
        ended_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    await service.handle_webhook(b"", {}, callback_secret=SECRET)

    stored = await _repos(pb).invoices.get(invoice.id)
    assert stored.status == "cancelled"
    assert await _job_status(pb) == "awaiting_payment"


async def test_subscription_restart_is_recorded(fake_pb: Any, pb: PocketBaseClient) -> None:
    provider = FakeProvider()
    service, invoice = await _paid_invoice(fake_pb, pb, provider)
    invoice = await _repos(pb).invoices.update(invoice.id, {"provider_subscription_id": "sub-1"})

    provider.notification = _notification(
        ProviderEventKind.SUBSCRIPTION_RESTARTED,
        token=invoice.correlation_token,
        sale_id=None,
        subscription_id="sub-1",
    )
    provider.subscription = ProviderSubscription(
        reference="sub-1", state=SubscriptionState.ALIVE, product_id="prod-1"
    )
    await service.handle_webhook(b"", {}, callback_secret=SECRET)

    stored = await _repos(pb).invoices.get(invoice.id)
    assert stored.metadata["subscription"]["last_event"] == "subscription_restarted"


async def test_provider_verification_failure_keeps_the_invoice_unpaid(
    fake_pb: Any, pb: PocketBaseClient
) -> None:
    _seed_settings(fake_pb)
    _seed_job(fake_pb)
    provider = FakeProvider()
    service = _service(pb, provider)
    invoice = await _start(pb, service)
    assert invoice is not None

    async def fail(reference: str) -> ProviderPayment:
        raise UpstreamError("Gumroad is unavailable.")

    provider.fetch_payment = fail  # type: ignore[method-assign]
    provider.notification = _notification(token=invoice.correlation_token)

    with pytest.raises(UpstreamError):
        await service.handle_webhook(b"", {}, callback_secret=SECRET)

    stored = await _repos(pb).invoices.get(invoice.id)
    assert stored.status == "pending"
    assert await _job_status(pb) == "awaiting_payment"
    event = next(iter(fake_pb.collections["billing_events"].values()))
    assert event["processed"] is False
    assert event["error"] == "UpstreamError"


async def test_invalid_callback_secret_is_refused_before_any_write(
    fake_pb: Any, pb: PocketBaseClient
) -> None:
    _seed_settings(fake_pb)
    _seed_job(fake_pb)
    service = _service(pb)
    invoice = await _start(pb, service)
    assert invoice is not None

    with pytest.raises(InvalidWebhookError):
        await service.handle_webhook(b"", {}, callback_secret="forged")

    assert "billing_events" not in fake_pb.collections
    assert (await _repos(pb).invoices.get(invoice.id)).status == "pending"


async def test_historical_payram_invoice_is_never_reinterpreted(
    fake_pb: Any, pb: PocketBaseClient
) -> None:
    _seed_settings(fake_pb)
    _seed_job(fake_pb)
    provider = FakeProvider()
    service = _service(pb, provider)
    invoice = await _start(pb, service)
    assert invoice is not None
    legacy = await _repos(pb).invoices.update(
        invoice.id,
        {
            "provider": "payram",
            "provider_reference": "old-payram-ref",
            "status": "paid",
        },
    )

    provider.payment = _payment(reference="old-payram-ref", token=None)
    assert (await service.reconcile(legacy)).status == "paid"

    with pytest.raises(ConflictError, match="retired"):
        await service.create_checkout(legacy, user_email="reader@example.com")


async def test_reconcile_finds_a_sale_by_the_correlation_token(
    fake_pb: Any, pb: PocketBaseClient
) -> None:
    _seed_settings(fake_pb)
    _seed_job(fake_pb)
    provider = FakeProvider()
    service = _service(pb, provider)
    invoice = await _start(pb, service)
    assert invoice is not None

    checked_out = await service.create_checkout(invoice, user_email="reader@example.com")
    provider.found = _payment(token=checked_out.correlation_token)
    reconciled = await service.reconcile(checked_out)

    assert reconciled.status == "paid"
    assert await _job_status(pb) == "queued"
