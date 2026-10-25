"""Provider-cost and flat per-book pricing engines."""

from __future__ import annotations

from app.billing.pricing import (
    BookPricing,
    BookPricingEngine,
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


def test_small_and_full_block_cost_the_same() -> None:
    engine = BookPricingEngine()
    assert engine.quote(BookPricing(), pages=100).price == 7.0
    assert engine.quote(BookPricing(), pages=1000).price == 7.0


def test_extra_blocks_are_charged() -> None:
    quote = BookPricingEngine().quote(BookPricing(), pages=1001)
    assert quote.blocks == 2
    assert quote.price == 14.0


def test_own_api_is_free() -> None:
    quote = BookPricingEngine().quote(
        BookPricing(billing_mode=BillingMode.OWN_API.value), pages=5000
    )
    assert quote.price == 0.0
    assert quote.blocks == 0


def test_empty_book_is_free() -> None:
    assert BookPricingEngine().quote(BookPricing(), pages=0).price == 0.0
