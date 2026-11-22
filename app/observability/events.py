"""Canonical structured events.

One small vocabulary keeps logs greppable and dashboards cheap. Emit through
:func:`emit` so the event name is always the ``event`` field. Never pass document
bodies, credentials, tokens or full prompts as fields.
"""

from __future__ import annotations

from typing import Any

from app.logging import get_logger

_logger = get_logger("book_fork.events")

# Auth lifecycle
LOGIN = "login"
LOGOUT = "logout"
ADMIN_ACCESS_DENIED = "admin_access_denied"

# Documents
UPLOAD = "upload"
DOCUMENT_DELETED = "document_deleted"

# Jobs
JOB_CREATED = "job_created"
JOB_CLAIMED = "job_claimed"
JOB_FAILED = "job_failed"
JOB_COMPLETED = "job_completed"
JOB_CANCELLED = "job_cancelled"
SEGMENT_FAILED = "segment_failed"

# Providers
PROVIDER_ERROR = "provider_error"
PROVIDER_RETRY = "provider_retry"
PROVIDER_CONNECTION_TESTED = "provider_connection_tested"

# Billing
BILLING_INVOICE_CREATED = "billing_invoice_created"
BILLING_CHECKOUT_CREATED = "billing_checkout_created"
BILLING_PAYMENT_RECEIVED = "billing_payment_received"
BILLING_SIGNATURE_FAILED = "billing_signature_failed"
BILLING_FULFILLED = "billing_fulfilled"
BILLING_FULFILLMENT_FAILED = "billing_fulfillment_failed"
BILLING_RECONCILED = "billing_reconciled"
BILLING_REFUNDED = "billing_refunded"
BILLING_DISPUTED = "billing_disputed"

# Retention / operations
RETENTION_SWEEP = "retention_sweep"


def emit(event: str, **fields: Any) -> None:
    """Emit a structured event at ``info`` level (event name becomes ``event``)."""
    _logger.info(event, **fields)
