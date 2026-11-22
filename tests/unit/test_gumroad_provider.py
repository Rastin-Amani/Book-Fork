"""Gumroad adapter: hosted checkout URL, Ping parsing, and API lookups.

Every test is offline; no real Gumroad credentials or purchases exist here.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from decimal import Decimal
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import pytest
from app.billing.payments.base import (
    CheckoutRequest,
    InvalidWebhookError,
    ProviderEventKind,
    ProviderState,
    SubscriptionState,
    WebhookPayloadError,
)
from app.billing.payments.gumroad import GumroadProvider
from app.exceptions import UpstreamError

TOKEN = "seller-access-token"
SECRET = "callback-secret-with-enough-entropy-123456"
PRODUCT = "prod-1"
PERMALINK = "book-fork"
FIELD = "Application Checkout Reference"


def _provider(
    handler: Callable[[httpx.Request], httpx.Response] | None = None,
    *,
    clock: Callable[[], float] | None = None,
) -> GumroadProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler or _unexpected))
    return GumroadProvider(
        access_token=TOKEN,
        webhook_secret=SECRET,
        product_id=PRODUCT,
        product_permalink=PERMALINK,
        client=client,
        clock=clock or (lambda: 1_700_000_000.0),
    )


def _unexpected(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"unexpected request: {request.method} {request.url}")


def _form(**fields: object) -> bytes:
    pairs: list[tuple[str, str]] = []
    for key, value in fields.items():
        if isinstance(value, dict):
            for child, child_value in value.items():
                pairs.append((f"{key}[{child}]", str(child_value)))
        else:
            pairs.append((key, str(value)))
    return urlencode(pairs).encode()


def _headers(content_type: str = "application/x-www-form-urlencoded") -> dict[str, str]:
    return {"Content-Type": content_type}


def _sale(**overrides: object) -> dict[str, object]:
    sale: dict[str, object] = {
        "id": "sale-1",
        "email": "reader@example.com",
        "purchase_email": "reader@example.com",
        "product_id": PRODUCT,
        "price": 700,
        "currency": "usd",
        "custom_fields": {FIELD: "token-1"},
        "refunded": False,
        "partially_refunded": False,
        "chargedback": False,
        "disputed": False,
        "dispute_won": False,
        "cancelled": False,
        "ended": False,
        "subscription_id": None,
        "created_at": "2026-01-01T00:00:00Z",
    }
    sale.update(overrides)
    return sale


# -- checkout ---------------------------------------------------------------
async def test_checkout_url_carries_email_price_and_custom_field() -> None:
    provider = _provider()
    session = await provider.create_checkout(
        CheckoutRequest(
            invoice_reference="BF-1",
            customer_email="reader@example.com",
            amount_usd=Decimal("7.00"),
            currency="USD",
            correlation_token="token-1",
        )
    )

    parts = urlsplit(session.url)
    query = parse_qs(parts.query)
    assert parts.scheme == "https"
    assert parts.hostname == "gumroad.com"
    assert parts.path == f"/l/{PERMALINK}"
    assert query["wanted"] == ["true"]
    assert query["email"] == ["reader@example.com"]
    assert query["price"] == ["7.00"]
    assert query[FIELD] == ["token-1"]
    assert provider.is_checkout_url_allowed(session.url)


async def test_checkout_rejects_non_usd_invoices() -> None:
    provider = _provider()
    with pytest.raises(UpstreamError, match="USD"):
        await provider.create_checkout(
            CheckoutRequest(
                invoice_reference="BF-1",
                customer_email="reader@example.com",
                amount_usd=Decimal("7.00"),
                currency="EUR",
                correlation_token="token-1",
            )
        )


def test_checkout_url_allowlist_is_gumroad_only() -> None:
    provider = _provider()
    assert provider.is_checkout_url_allowed("https://gumroad.com/l/book")
    assert not provider.is_checkout_url_allowed("https://gumroad.com.evil.test/l/book")
    assert not provider.is_checkout_url_allowed("http://gumroad.com/l/book")
    assert not provider.is_checkout_url_allowed("https://example.com/l/book")


# -- webhook ----------------------------------------------------------------
def test_valid_ping_is_parsed_without_trusting_url_params() -> None:
    provider = _provider()
    body = _form(
        sale_id="sale-1",
        product_id=PRODUCT,
        price=700,
        test="false",
        custom_fields={FIELD: "token-1"},
        url_params={FIELD: "attacker-token"},
    )

    notification = provider.verify_webhook(body, _headers(), SECRET)

    assert notification.kind is ProviderEventKind.SALE
    assert notification.sale_id == "sale-1"
    assert notification.invoice_reference == "token-1"
    assert notification.event_key == "sale:sale-1"


def test_custom_fields_may_arrive_as_a_literal_string() -> None:
    provider = _provider()
    body = _form(
        sale_id="sale-1",
        custom_fields=json.dumps({FIELD: "token-1"}).replace('"', "'"),
    )

    notification = provider.verify_webhook(body, _headers(), SECRET)

    assert notification.invoice_reference == "token-1"


def test_refund_and_dispute_pings_are_classified_by_their_flags() -> None:
    provider = _provider()

    refund = provider.verify_webhook(
        _form(sale_id="sale-1", refunded="true", custom_fields={FIELD: "token-1"}),
        _headers(),
        SECRET,
    )
    assert refund.kind is ProviderEventKind.REFUND
    assert refund.refunded is True

    dispute = provider.verify_webhook(_form(sale_id="sale-1", disputed="true"), _headers(), SECRET)
    assert dispute.kind is ProviderEventKind.DISPUTE

    won = provider.verify_webhook(
        _form(sale_id="sale-1", disputed="true", dispute_won="true"), _headers(), SECRET
    )
    assert won.kind is ProviderEventKind.DISPUTE_WON


def test_subscription_events_are_inferred_from_their_fields() -> None:
    provider = _provider()

    ended = provider.verify_webhook(
        _form(subscription_id="sub-1", ended_at="2026-01-01T00:00:00Z"),
        _headers(),
        SECRET,
    )
    assert ended.kind is ProviderEventKind.SUBSCRIPTION_ENDED

    cancelled = provider.verify_webhook(
        _form(subscription_id="sub-1", cancelled="true", cancelled_at="2026-02-01T00:00:00Z"),
        _headers(),
        SECRET,
    )
    assert cancelled.kind is ProviderEventKind.CANCELLATION

    restarted = provider.verify_webhook(
        _form(subscription_id="sub-1", restarted_at="2026-03-01T00:00:00Z"),
        _headers(),
        SECRET,
    )
    assert restarted.kind is ProviderEventKind.SUBSCRIPTION_RESTARTED

    updated = provider.verify_webhook(
        _form(
            subscription_id="sub-1",
            type="upgrade",
            effective_as_of="2026-03-01T00:00:00Z",
            new_plan=json.dumps({"price_cents": "1200"}),
        ),
        _headers(),
        SECRET,
    )
    assert updated.kind is ProviderEventKind.SUBSCRIPTION_UPDATED


def test_explicit_resource_name_wins() -> None:
    provider = _provider()
    body = _form(resource_name="dispute_won", sale_id="sale-1")
    assert provider.verify_webhook(body, _headers(), SECRET).kind is ProviderEventKind.DISPUTE_WON


def test_wrong_callback_secret_is_refused() -> None:
    provider = _provider()
    with pytest.raises(InvalidWebhookError):
        provider.verify_webhook(_form(sale_id="sale-1"), _headers(), "wrong")
    with pytest.raises(InvalidWebhookError):
        provider.verify_webhook(_form(sale_id="sale-1"), _headers(), None)


def test_non_form_content_type_is_refused() -> None:
    provider = _provider()
    with pytest.raises(WebhookPayloadError):
        provider.verify_webhook(b'{"sale_id": "sale-1"}', _headers("application/json"), SECRET)


def test_sale_event_without_sale_id_is_refused() -> None:
    provider = _provider()
    with pytest.raises(WebhookPayloadError, match="sale id"):
        provider.verify_webhook(_form(resource_name="sale"), _headers(), SECRET)


def test_unknown_resource_is_refused() -> None:
    provider = _provider()
    with pytest.raises(WebhookPayloadError, match="unknown"):
        provider.verify_webhook(_form(resource_name="chargeback"), _headers(), SECRET)


def test_signed_ping_is_verified_and_stale_or_forged_pings_are_refused() -> None:
    now = 1_700_000_000
    provider = _provider(clock=lambda: float(now))
    body = _form(sale_id="sale-1")

    def signature(timestamp: int, payload: bytes) -> str:
        digest = hmac.new(
            SECRET.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256
        ).hexdigest()
        return f"t={timestamp},v1={digest}"

    headers = {**_headers(), "X-Gumroad-Signature": signature(now, body)}
    assert provider.verify_webhook(body, headers, SECRET).sale_id == "sale-1"

    stale = {**_headers(), "X-Gumroad-Signature": signature(now - 301, body)}
    with pytest.raises(InvalidWebhookError):
        provider.verify_webhook(body, stale, SECRET)

    forged = {**_headers(), "X-Gumroad-Signature": f"t={now},v1=deadbeef"}
    with pytest.raises(InvalidWebhookError):
        provider.verify_webhook(body, forged, SECRET)


# -- authoritative sale -----------------------------------------------------
async def test_fetch_payment_converts_cents_and_reads_state() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/sales/sale-1"
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        return httpx.Response(
            200,
            json={"success": True, "sale": _sale(disputed=True, dispute_won=False)},
        )

    payment = await _provider(handler).fetch_payment("sale-1")

    assert payment.reference == "sale-1"
    assert payment.product_id == PRODUCT
    assert payment.invoice_reference == "token-1"
    assert payment.filled_amount_usd == Decimal("7")
    assert payment.currency == "USD"
    assert payment.state is ProviderState.DISPUTED
    assert payment.purchaser_email == "reader@example.com"


async def test_fetch_payment_marks_refunds_and_chargebacks() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "sale": _sale(chargedback=True)})

    payment = await _provider(handler).fetch_payment("sale-1")
    assert payment.chargedback is True
    assert payment.state is ProviderState.REFUNDED


async def test_fetch_payment_rejects_malformed_and_failed_responses() -> None:
    def malformed(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True})

    with pytest.raises(UpstreamError):
        await _provider(malformed).fetch_payment("sale-1")

    def failed(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"success": False, "message": "no sale"})

    with pytest.raises(UpstreamError):
        await _provider(failed).fetch_payment("sale-1")


async def test_fetch_subscription_maps_documented_statuses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/subscribers/sub-1"
        return httpx.Response(
            200,
            json={
                "success": True,
                "subscribers": {
                    "id": "sub-1",
                    "product_id": PRODUCT,
                    "status": "pending_cancellation",
                    "recurrence": "monthly",
                    "user_email": "reader@example.com",
                    "cancelled_at": "2099-12-01T00:00:00Z",
                },
            },
        )

    subscription = await _provider(handler).fetch_subscription("sub-1")

    assert subscription.reference == "sub-1"
    assert subscription.state is SubscriptionState.PENDING_CANCELLATION
    assert subscription.recurrence == "monthly"
    assert subscription.cancelled_at is not None


async def test_find_payment_matches_the_custom_field_and_rereads_the_sale() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/sales":
            assert request.url.params["email"] == "reader@example.com"
            assert request.url.params["product_id"] == PRODUCT
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "sales": [
                        _sale(id="sale-0", custom_fields={FIELD: "other"}),
                        _sale(id="sale-1"),
                    ],
                },
            )
        assert request.url.path == "/v2/sales/sale-1"
        return httpx.Response(200, json={"success": True, "sale": _sale()})

    payment = await _provider(handler).find_payment("token-1", "reader@example.com")

    assert payment is not None
    assert payment.reference == "sale-1"


async def test_find_payment_returns_none_when_no_sale_carries_the_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"success": True, "sales": [_sale(custom_fields={FIELD: "other"})]}
        )

    assert await _provider(handler).find_payment("token-1", "reader@example.com") is None
