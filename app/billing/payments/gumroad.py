"""Gumroad payment adapter (hosted checkout + authoritative API lookups).

Contract verified against the current Gumroad API and Ping documentation:

* Checkout is hosted by Gumroad. There is no server-side checkout-session API.
  The URL is built from the product permalink plus documented URL parameters:
  ``wanted=true``, ``email``, ``price`` (major units, for a pay-what-you-want
  product), and one custom field carrying the invoice's correlation token.
* Sales: ``GET /v2/sales/:id``; ``GET /v2/sales?email=...&product_id=...``.
  Amounts are integers in **USD cents** whatever the listing currency is.
* Subscribers: ``GET /v2/subscribers/:id``.
* Pings and resource-subscription notifications are
  ``application/x-www-form-urlencoded``. API resource subscriptions are not
  signed; the endpoint URL carries our own high-entropy secret and every
  notification is re-verified through the API before fulfillment. Gumroad can
  optionally sign *Ping URL* deliveries with ``X-Gumroad-Signature``; that is
  verified when present.
"""

from __future__ import annotations

import ast
import hashlib
import hmac
import json
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlsplit

import httpx

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
    WebhookPayloadError,
)
from app.exceptions import UpstreamError
from app.logging import get_logger

logger = get_logger(__name__)

DEFAULT_API_BASE_URL = "https://api.gumroad.com"
DEFAULT_CUSTOM_FIELD = "Application Checkout Reference"
CHECKOUT_HOST = "gumroad.com"

_SALE_EVENTS = frozenset(
    {
        ProviderEventKind.SALE,
        ProviderEventKind.REFUND,
        ProviderEventKind.DISPUTE,
        ProviderEventKind.DISPUTE_WON,
    }
)
_SUBSCRIPTION_STATES: dict[str, SubscriptionState] = {
    "alive": SubscriptionState.ALIVE,
    "pending_cancellation": SubscriptionState.PENDING_CANCELLATION,
    "pending_failure": SubscriptionState.PENDING_FAILURE,
    "failed_payment": SubscriptionState.FAILED_PAYMENT,
    "fixed_subscription_period_ended": SubscriptionState.ENDED,
    "ended": SubscriptionState.ENDED,
    "cancelled": SubscriptionState.CANCELLED,
}


class GumroadProvider:
    name = "gumroad"

    def __init__(
        self,
        *,
        access_token: str,
        webhook_secret: str,
        product_id: str,
        product_permalink: str,
        client: httpx.AsyncClient,
        custom_field_name: str = DEFAULT_CUSTOM_FIELD,
        base_url: str = DEFAULT_API_BASE_URL,
        timeout_seconds: float = 10.0,
        allow_test_sales: bool = False,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.product_id = product_id
        self.allow_test_sales = allow_test_sales
        self._access_token = access_token
        self._webhook_secret = webhook_secret
        self._product_permalink = product_permalink
        self._custom_field_name = custom_field_name
        self._base_url = base_url.rstrip("/")
        self._client = client
        self._timeout = timeout_seconds
        self._clock = clock

    # -- checkout ------------------------------------------------------------
    async def create_checkout(self, request: CheckoutRequest) -> CheckoutSession:
        if request.currency.upper() != "USD":
            raise UpstreamError("Gumroad checkout supports USD invoices only.")
        if request.amount_usd <= 0:
            raise UpstreamError("The invoice amount must be positive.")
        params = [
            ("wanted", "true"),
            ("email", request.customer_email),
            (self._custom_field_name, request.correlation_token),
            ("price", _major_units(request.amount_usd)),
        ]
        url = (
            f"https://{CHECKOUT_HOST}/l/{quote(self._product_permalink, safe='')}"
            f"?{urlencode(params, quote_via=quote)}"
        )
        if not self.is_checkout_url_allowed(url):
            # The URL is built locally; this guard catches a misconfigured
            # permalink before a customer is redirected anywhere else.
            raise UpstreamError("The payment provider returned an untrusted checkout URL.")
        return CheckoutSession(url=url)

    # -- authoritative sale --------------------------------------------------
    async def fetch_payment(self, reference: str) -> ProviderPayment:
        data = await self._get(f"/v2/sales/{quote(reference, safe='')}")
        sale = data.get("sale")
        if not isinstance(sale, dict):
            logger.warning("gumroad_sale_malformed", sale_id=reference)
            raise UpstreamError("The payment provider returned malformed data.")
        return _sale(sale, custom_field=self._custom_field_name)

    async def find_payment(
        self, correlation_token: str, customer_email: str
    ) -> ProviderPayment | None:
        """Find a sale by the custom field when a notification was missed.

        The list endpoint is filtered by buyer email and product, then each row
        is checked for our token. The returned sale is re-read by id so the
        result is the same authoritative representation as ``fetch_payment``.
        """
        page_key: str | None = None
        for _ in range(5):
            params: dict[str, str] = {"email": customer_email, "product_id": self.product_id}
            if page_key:
                params["page_key"] = page_key
            data = await self._get("/v2/sales", params=params)
            sales = data.get("sales")
            if isinstance(sales, list):
                for sale in sales:
                    if not isinstance(sale, dict):
                        continue
                    custom = _mapping(sale.get("custom_fields"))
                    if _text(custom.get(self._custom_field_name)) != correlation_token:
                        continue
                    sale_id = _text(sale.get("id"))
                    if sale_id:
                        return await self.fetch_payment(sale_id)
            page_key = _text(data.get("next_page_key"))
            if not page_key:
                break
        return None

    # -- authoritative subscription -----------------------------------------
    async def fetch_subscription(self, reference: str) -> ProviderSubscription:
        data = await self._get(f"/v2/subscribers/{quote(reference, safe='')}")
        record = data.get("subscribers") or data.get("subscriber")
        if not isinstance(record, dict):
            logger.warning("gumroad_subscription_malformed", subscription_id=reference)
            raise UpstreamError("The payment provider returned malformed data.")
        return _subscription(record)

    # -- webhook -------------------------------------------------------------
    def verify_webhook(
        self,
        raw_body: bytes,
        headers: Mapping[str, str],
        callback_secret: str | None,
    ) -> ProviderNotification:
        # Resource subscriptions are not signed by Gumroad. The URL secret is
        # the local credential, and it is compared in constant time.
        if not callback_secret or not hmac.compare_digest(callback_secret, self._webhook_secret):
            raise InvalidWebhookError()

        lowered = {key.lower(): value for key, value in headers.items()}
        content_type = lowered.get("content-type", "").lower()
        if "application/x-www-form-urlencoded" not in content_type:
            raise WebhookPayloadError("The webhook must be form-encoded.")

        signature = lowered.get("x-gumroad-signature", "").strip()
        if signature:
            self._verify_ping_signature(raw_body, signature)

        fields = _parse_form(raw_body)
        kind = _event_kind(fields)
        sale_id = _text(fields.get("sale_id"))
        subscription_id = _text(fields.get("subscription_id"))
        product_id = _text(fields.get("product_id"))
        test = _bool(fields.get("test"))

        if kind in _SALE_EVENTS:
            if not sale_id:
                raise WebhookPayloadError("The webhook has no sale id.")
        elif not subscription_id:
            raise WebhookPayloadError("The webhook has no subscription id.")

        # Only the sale's own custom fields are authoritative. A URL parameter
        # is attacker-controlled, so it is never used to pick an invoice.
        custom = _nested(fields.get("custom_fields"))
        token = _text(custom.get(self._custom_field_name))

        return ProviderNotification(
            kind=kind,
            event_key=_event_key(kind, fields, sale_id, subscription_id, raw_body),
            sale_id=sale_id,
            subscription_id=subscription_id,
            product_id=product_id,
            invoice_reference=token,
            test=test,
            refunded=_bool(fields.get("refunded")),
            raw=fields,
        )

    def _verify_ping_signature(self, raw_body: bytes, header: str) -> None:
        parts = {}
        for item in header.split(","):
            key, separator, value = item.partition("=")
            if separator:
                parts[key.strip()] = value.strip()
        timestamp = parts.get("t", "")
        signature = parts.get("v1", "")
        try:
            sent_at = int(timestamp)
        except ValueError as exc:
            raise InvalidWebhookError() from exc
        if abs(self._clock() - sent_at) > 300:
            raise InvalidWebhookError()
        expected = hmac.new(
            self._webhook_secret.encode(), f"{timestamp}.".encode() + raw_body, hashlib.sha256
        ).hexdigest()
        if not signature or not hmac.compare_digest(signature, expected):
            raise InvalidWebhookError()

    # -- redirect safety -----------------------------------------------------
    def is_checkout_url_allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        return (
            parts.scheme == "https"
            and (host == CHECKOUT_HOST or host.endswith(f".{CHECKOUT_HOST}"))
            and parts.path.startswith("/l/")
        )

    # -- transport -----------------------------------------------------------
    async def _get(self, path: str, *, params: dict[str, str] | None = None) -> dict[str, Any]:
        try:
            response = await self._client.get(
                f"{self._base_url}{path}",
                headers={
                    "Authorization": f"Bearer {self._access_token}",
                    "Accept": "application/json",
                },
                params=params,
                timeout=self._timeout,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            logger.warning("gumroad_transport_error", path=path, error=type(exc).__name__)
            raise UpstreamError("The payment provider is unavailable.") from exc

        if response.status_code >= 400:
            # Never log the response body: it can contain buyer details.
            logger.warning("gumroad_request_failed", path=path, status=response.status_code)
            raise UpstreamError("The payment provider rejected the request.")
        try:
            data = response.json()
        except ValueError as exc:
            raise UpstreamError("The payment provider returned malformed data.") from exc
        if not isinstance(data, dict) or data.get("success") is False:
            raise UpstreamError("The payment provider returned malformed data.")
        return data


def _sale(record: Mapping[str, Any], *, custom_field: str) -> ProviderPayment:
    sale_id = _text(record.get("id"))
    if not sale_id:
        raise UpstreamError("The payment provider returned a sale without an id.")
    cents = _int(record.get("price"))
    paid = Decimal(cents) / 100 if cents is not None else None
    refunded = _bool(record.get("refunded"))
    partially_refunded = _bool(record.get("partially_refunded"))
    chargedback = _bool(record.get("chargedback"))
    disputed = _bool(record.get("disputed"))
    dispute_won = _bool(record.get("dispute_won"))
    cancelled = _bool(record.get("cancelled"))
    ended = _bool(record.get("ended"))
    custom = _mapping(record.get("custom_fields"))
    if refunded or chargedback:
        state = ProviderState.REFUNDED
    elif disputed and not dispute_won:
        state = ProviderState.DISPUTED
    elif cancelled or ended:
        state = ProviderState.CANCELLED
    else:
        state = ProviderState.PAID
    return ProviderPayment(
        reference=sale_id,
        invoice_reference=_text(custom.get(custom_field)),
        state=state,
        product_id=_text(record.get("product_id")),
        requested_amount=paid,
        filled_amount_usd=paid,
        currency="USD",
        subscription_id=_text(record.get("subscription_id")),
        purchaser_email=_text(record.get("purchase_email") or record.get("email")),
        # ``is_recurring_billing`` is true for every charge of a membership, so
        # only ``recurring_charge`` marks a renewal of an existing subscription.
        recurring=_bool(record.get("recurring_charge")),
        refunded=refunded,
        partially_refunded=partially_refunded,
        chargedback=chargedback,
        disputed=disputed,
        dispute_won=dispute_won,
        cancelled=cancelled,
        ended=ended,
        test=_bool(record.get("test")),
        timestamp=_epoch(record.get("created_at")),
        raw=dict(record),
    )


def _subscription(record: Mapping[str, Any]) -> ProviderSubscription:
    reference = _text(record.get("id"))
    if not reference:
        raise UpstreamError("The payment provider returned a subscription without an id.")
    cancelled_at = _datetime(record.get("cancelled_at"))
    ended_at = _datetime(record.get("ended_at"))
    failed_at = _datetime(record.get("failed_at"))
    state = _SUBSCRIPTION_STATES.get(
        (_text(record.get("status")) or "").lower(), SubscriptionState.UNKNOWN
    )
    # Gumroad terminates a subscription when any of these timestamps is
    # populated and in the past, even if the status string lags behind.
    now = datetime.now(UTC)
    if ended_at is not None and ended_at <= now:
        state = SubscriptionState.ENDED
    elif cancelled_at is not None and cancelled_at <= now:
        state = SubscriptionState.CANCELLED
    elif failed_at is not None and failed_at <= now:
        state = SubscriptionState.FAILED_PAYMENT
    return ProviderSubscription(
        reference=reference,
        state=state,
        product_id=_text(record.get("product_id")),
        recurrence=_text(record.get("recurrence")),
        purchaser_email=_text(record.get("user_email")),
        cancelled_at=cancelled_at,
        ended_at=ended_at,
        failed_at=failed_at,
        user_requested_cancellation_at=_datetime(record.get("user_requested_cancellation_at")),
        raw=dict(record),
    )


def _parse_form(raw_body: bytes) -> dict[str, Any]:
    try:
        text = raw_body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WebhookPayloadError("The webhook payload is not UTF-8.") from exc
    try:
        pairs = parse_qs(text, keep_blank_values=True, strict_parsing=False)
    except ValueError as exc:
        raise WebhookPayloadError("The webhook payload is invalid.") from exc
    if not pairs:
        raise WebhookPayloadError("The webhook payload is empty.")

    fields: dict[str, Any] = {}
    for key, values in pairs.items():
        value = values[-1]
        bracket = key.find("[")
        if bracket > 0 and key.endswith("]"):
            parent = key[:bracket]
            child = key[bracket + 1 : -1]
            if parent and child:
                nested = fields.get(parent)
                if not isinstance(nested, dict):
                    nested = {}
                    fields[parent] = nested
                nested[child] = value
                continue
        fields[key] = value
    return fields


def _nested(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    text = _text(value)
    if not text or not text.startswith("{"):
        return {}
    for parser in (json.loads, ast.literal_eval):
        try:
            parsed = parser(text)
        except ValueError, SyntaxError, TypeError:
            continue
        if isinstance(parsed, dict):
            return {str(key): item for key, item in parsed.items()}
    return {}


def _event_kind(fields: Mapping[str, Any]) -> ProviderEventKind:
    """Name the event from ``resource_name`` or, for a Ping, from its fields.

    Sale, refund, dispute and dispute-won notifications share the Ping format.
    Subscription notifications document their own fields but not always a
    ``resource_name``, so the payload shape is the fallback.
    """
    explicit = _text(fields.get("resource_name"))
    if explicit:
        try:
            return ProviderEventKind(explicit.lower())
        except ValueError as exc:
            raise WebhookPayloadError("The webhook resource is unknown.") from exc
    if _text(fields.get("restarted_at")):
        return ProviderEventKind.SUBSCRIPTION_RESTARTED
    if _text(fields.get("ended_at")) or _text(fields.get("ended_reason")):
        return ProviderEventKind.SUBSCRIPTION_ENDED
    if _text(fields.get("cancelled_at")) or _bool(fields.get("cancelled")):
        return ProviderEventKind.CANCELLATION
    if _text(fields.get("type")) and _text(fields.get("effective_as_of")):
        return ProviderEventKind.SUBSCRIPTION_UPDATED
    if _text(fields.get("sale_id")):
        if _bool(fields.get("dispute_won")):
            return ProviderEventKind.DISPUTE_WON
        if _bool(fields.get("disputed")):
            return ProviderEventKind.DISPUTE
        if _bool(fields.get("refunded")) or _bool(fields.get("chargedback")):
            return ProviderEventKind.REFUND
        return ProviderEventKind.SALE
    if _text(fields.get("subscription_id")):
        return ProviderEventKind.SUBSCRIPTION_UPDATED
    raise WebhookPayloadError("The webhook payload is not a Gumroad notification.")


def _event_key(
    kind: ProviderEventKind,
    fields: Mapping[str, Any],
    sale_id: str | None,
    subscription_id: str | None,
    raw_body: bytes,
) -> str:
    if kind in _SALE_EVENTS:
        return f"{kind.value}:{sale_id}"
    if kind == ProviderEventKind.CANCELLATION:
        return f"{kind.value}:{subscription_id}:{_text(fields.get('cancelled_at')) or '-'}"
    if kind == ProviderEventKind.SUBSCRIPTION_UPDATED:
        return (
            f"{kind.value}:{subscription_id}:"
            f"{_text(fields.get('effective_as_of')) or '-'}:{_text(fields.get('type')) or '-'}"
        )
    if kind == ProviderEventKind.SUBSCRIPTION_ENDED:
        return f"{kind.value}:{subscription_id}:{_text(fields.get('ended_at')) or '-'}"
    if kind == ProviderEventKind.SUBSCRIPTION_RESTARTED:
        return f"{kind.value}:{subscription_id}:{_text(fields.get('restarted_at')) or '-'}"
    return f"{kind.value}:{subscription_id}:{hashlib.sha256(raw_body).hexdigest()[:16]}"


def _major_units(amount: Decimal) -> str:
    return f"{amount.quantize(Decimal('0.01')):.2f}"


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _int(value: object) -> int | None:
    try:
        return int(str(value)) if value not in (None, "") else None
    except TypeError, ValueError:
        return None


def _datetime(value: object) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _epoch(value: object) -> int | None:
    parsed = _datetime(value)
    return int(parsed.timestamp()) if parsed is not None else None
