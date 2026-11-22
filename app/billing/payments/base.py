"""Payment-provider boundary.

Billing code depends on these normalized types, never on a provider's raw
response schema. A new provider implements the same protocol and the invoice,
webhook, and entitlement code stays unchanged.

The provider is never the source of truth for a payment: a notification is a
hint that something happened, and the service re-reads the sale or subscription
from the provider's API before granting or revoking anything.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from app.exceptions import BookForkError


class ProviderState(StrEnum):
    PENDING = "pending"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    OVERPAID = "overpaid"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    DISPUTED = "disputed"
    UNKNOWN = "unknown"


class ProviderEventKind(StrEnum):
    SALE = "sale"
    REFUND = "refund"
    DISPUTE = "dispute"
    DISPUTE_WON = "dispute_won"
    CANCELLATION = "cancellation"
    SUBSCRIPTION_UPDATED = "subscription_updated"
    SUBSCRIPTION_ENDED = "subscription_ended"
    SUBSCRIPTION_RESTARTED = "subscription_restarted"


class SubscriptionState(StrEnum):
    ALIVE = "alive"
    PENDING_CANCELLATION = "pending_cancellation"
    PENDING_FAILURE = "pending_failure"
    FAILED_PAYMENT = "failed_payment"
    ENDED = "ended"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class InvalidWebhookError(BookForkError):
    status_code = 401
    code = "INVALID_WEBHOOK"
    message = "The webhook could not be verified."


class WebhookPayloadError(BookForkError):
    status_code = 400
    code = "INVALID_WEBHOOK_PAYLOAD"
    message = "The webhook payload is invalid."


@dataclass(frozen=True, slots=True)
class CheckoutRequest:
    invoice_reference: str
    customer_email: str
    amount_usd: Decimal
    currency: str
    correlation_token: str


@dataclass(frozen=True, slots=True)
class CheckoutSession:
    url: str
    # Providers that create a server-side session return its id here. Hosted
    # checkouts (Gumroad) have no reference until the first sale exists.
    reference: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderPayment:
    reference: str
    invoice_reference: str | None
    state: ProviderState
    product_id: str | None = None
    requested_amount: Decimal | None = None
    filled_amount_usd: Decimal | None = None
    currency: str | None = None
    subscription_id: str | None = None
    purchaser_email: str | None = None
    recurring: bool = False
    refunded: bool = False
    partially_refunded: bool = False
    chargedback: bool = False
    disputed: bool = False
    dispute_won: bool = False
    cancelled: bool = False
    ended: bool = False
    test: bool = False
    timestamp: int | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderSubscription:
    reference: str
    state: SubscriptionState
    product_id: str | None = None
    recurrence: str | None = None
    purchaser_email: str | None = None
    cancelled_at: datetime | None = None
    ended_at: datetime | None = None
    failed_at: datetime | None = None
    user_requested_cancellation_at: datetime | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderNotification:
    """A parsed, locally authenticated provider webhook.

    This is still untrusted: the service must fetch the sale or subscription
    from the provider API before changing an invoice.
    """

    kind: ProviderEventKind
    event_key: str
    sale_id: str | None = None
    subscription_id: str | None = None
    product_id: str | None = None
    invoice_reference: str | None = None
    test: bool = False
    # The sale API does not expose a reliable full-refund flag, so a refund
    # notification carries the hint. The sale is still re-read by id first.
    refunded: bool = False
    raw: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class PaymentProvider(Protocol):
    name: str
    product_id: str
    allow_test_sales: bool

    async def create_checkout(self, request: CheckoutRequest) -> CheckoutSession: ...

    async def fetch_payment(self, reference: str) -> ProviderPayment: ...

    async def find_payment(
        self, correlation_token: str, customer_email: str
    ) -> ProviderPayment | None: ...

    async def fetch_subscription(self, reference: str) -> ProviderSubscription: ...

    def verify_webhook(
        self,
        raw_body: bytes,
        headers: Mapping[str, str],
        callback_secret: str | None,
    ) -> ProviderNotification: ...

    def is_checkout_url_allowed(self, url: str) -> bool: ...
