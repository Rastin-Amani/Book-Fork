"""Provider-cost and credit pricing engines."""

from __future__ import annotations

from app.billing.pricing import (
    CreditPricing,
    CreditPricingEngine,
    ProviderPricing,
    ProviderPricingEngine,
)
from app.schemas.providers import BillingMode


def test_provider_cost_from_tokens() -> None:
    pricing = ProviderPricing(
        input_cost_per_million_tokens=3.0, output_cost_per_million_tokens=15.0
    )
    cost = ProviderPricingEngine().compute(pricing, input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost == 18.0


def test_flat_request_cost() -> None:
    pricing = ProviderPricing(request_cost=0.01)
    assert (
        ProviderPricingEngine().compute(pricing, input_tokens=0, output_tokens=0, requests=3)
        == 0.03
    )


def test_managed_credits_from_tokens() -> None:
    credits = CreditPricingEngine().compute(
        CreditPricing(billing_mode=BillingMode.MANAGED.value, credits_per_1000_tokens=2.0),
        input_tokens=1000,
        output_tokens=1000,
    )
    assert credits == 4.0


def test_own_api_mode_consumes_no_credits() -> None:
    credits = CreditPricingEngine().compute(
        CreditPricing(billing_mode=BillingMode.OWN_API.value, credits_per_1000_tokens=2.0),
        input_tokens=1000,
        output_tokens=1000,
        provider_cost=5.0,
    )
    assert credits == 0.0


def test_provider_cost_markup() -> None:
    credits = CreditPricingEngine().compute(
        CreditPricing(
            billing_mode=BillingMode.MANAGED.value,
            credits_per_1000_tokens=0.0,
            provider_cost_markup=10.0,
        ),
        input_tokens=0,
        output_tokens=0,
        provider_cost=1.5,
    )
    assert credits == 15.0
