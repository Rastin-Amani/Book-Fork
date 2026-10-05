"""Pre-translation estimation."""

from __future__ import annotations

from app.billing.estimation import estimate_from_texts
from app.billing.pricing import CreditPricing, ProviderPricing
from app.schemas.providers import BillingMode


def test_estimate_reports_words_tokens_cost_credits() -> None:
    estimate = estimate_from_texts(
        ["hello world", "another sentence here"],
        provider_pricing=ProviderPricing(
            input_cost_per_million_tokens=1.0, output_cost_per_million_tokens=2.0
        ),
        credit_pricing=CreditPricing(credits_per_1000_tokens=1.0),
    )
    assert estimate.estimated is True
    assert estimate.words == 5
    assert estimate.characters == len("hello world") + len("another sentence here")
    assert estimate.input_tokens >= 1
    assert estimate.output_tokens == estimate.input_tokens
    assert estimate.provider_cost > 0
    assert estimate.credits > 0


def test_own_api_estimate_has_no_credits_but_provider_cost() -> None:
    estimate = estimate_from_texts(
        ["hello world"],
        provider_pricing=ProviderPricing(input_cost_per_million_tokens=100.0),
        credit_pricing=CreditPricing(billing_mode=BillingMode.OWN_API.value),
    )
    assert estimate.credits == 0.0
    assert estimate.provider_cost > 0


def test_empty_input() -> None:
    estimate = estimate_from_texts(
        [], provider_pricing=ProviderPricing(), credit_pricing=CreditPricing()
    )
    assert estimate.words == 0 and estimate.characters == 0 and estimate.credits == 0.0
