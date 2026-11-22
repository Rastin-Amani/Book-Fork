"""Build the configured payment provider, or ``None`` when billing is off."""

from __future__ import annotations

import httpx

from app.billing.payments.base import PaymentProvider
from app.billing.payments.gumroad import GumroadProvider
from app.config import Settings
from app.exceptions import ConfigurationError


def build_payment_provider(settings: Settings, client: httpx.AsyncClient) -> PaymentProvider | None:
    if not settings.billing_enabled:
        # Missing Gumroad credentials must never turn billing on by themselves.
        return None
    if settings.payment_provider != "gumroad":
        raise ConfigurationError(
            "Billing is enabled but PAYMENT_PROVIDER is not 'gumroad'. "
            "Gumroad is the only supported payment provider."
        )
    if (
        settings.gumroad_access_token is None
        or settings.gumroad_webhook_secret is None
        or not settings.gumroad_product_id
        or not settings.gumroad_product_permalink
    ):
        # Settings validation normally catches this at startup; keep the guard
        # so a hand-built context can never silently take free payments.
        raise ConfigurationError(
            "Billing is enabled but Gumroad is not configured "
            "(GUMROAD_ACCESS_TOKEN, GUMROAD_WEBHOOK_SECRET, GUMROAD_PRODUCT_ID and "
            "GUMROAD_PRODUCT_PERMALINK are required)."
        )
    return GumroadProvider(
        access_token=settings.gumroad_access_token.get_secret_value(),
        webhook_secret=settings.gumroad_webhook_secret.get_secret_value(),
        product_id=settings.gumroad_product_id,
        product_permalink=settings.gumroad_product_permalink,
        custom_field_name=settings.gumroad_custom_field_name,
        client=client,
        timeout_seconds=settings.gumroad_timeout_seconds,
        allow_test_sales=settings.gumroad_allow_test_sales,
    )
