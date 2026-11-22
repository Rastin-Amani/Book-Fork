"""Billing records: invoices, webhook events, and free-allowance claims.

Money is stored in the invoice currency (USD for Gumroad) and is never mixed
with provider cost. Credits are not used by this product: a paid managed book
is an entitlement attached to one translation job. ``payram`` remains a valid
provider value so historical rows survive the Gumroad migration.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from app.schemas.base import Record


class InvoiceStatus(StrEnum):
    PENDING = "pending"
    AWAITING_PAYMENT = "awaiting_payment"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    CANCELLED = "cancelled"
    FAILED = "failed"
    REFUNDED = "refunded"
    REVIEW = "review"


class InvoiceProvider(StrEnum):
    GUMROAD = "gumroad"
    # Historical provider: kept so old invoices and events stay readable.
    PAYRAM = "payram"
    FREE = "free"
    NONE = "none"


class ProductType(StrEnum):
    MANAGED_BOOK = "managed_book"


class BillingInvoice(Record):
    workspace: str
    created_by: str | None = None
    job: str | None = None
    reference: str
    product_type: ProductType = ProductType.MANAGED_BOOK
    product_name: str
    amount: float
    currency: str = "USD"
    status: InvoiceStatus = InvoiceStatus.PENDING
    provider: InvoiceProvider = InvoiceProvider.NONE
    provider_reference: str | None = None
    provider_subscription_id: str | None = None
    # High-entropy, single-use token placed in the Gumroad custom field. It
    # correlates the hosted checkout with this invoice without exposing ids.
    correlation_token: str | None = None
    checkout_url: str | None = None
    paid_amount: float | None = None
    paid_currency: str | None = None
    expires_at: datetime | None = None
    paid_at: datetime | None = None
    refunded_at: datetime | None = None
    fulfilled_at: datetime | None = None
    failure_reason: str | None = None
    product_snapshot: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BillingEvent(Record):
    provider: str
    event_key: str
    invoice: str | None = None
    event_type: str = "payment"
    provider_reference: str | None = None
    status: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    processed: bool = False
    processed_at: datetime | None = None
    error: str | None = None


class BillingFreeClaim(Record):
    workspace: str
    kind: str = ProductType.MANAGED_BOOK.value
    slot: int
    invoice: str | None = None
    job: str | None = None
