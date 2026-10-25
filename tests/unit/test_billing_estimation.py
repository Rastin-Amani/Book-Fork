"""Pre-translation estimation."""

from __future__ import annotations

from app.billing.estimation import estimate_from_texts
from app.billing.pricing import BookPricing, ProviderPricing
from app.schemas.providers import BillingMode


def test_estimate_reports_words_tokens_cost_and_price() -> None:
    estimate = estimate_from_texts(
        ["hello world", "another sentence here"],
        provider_pricing=ProviderPricing(
            input_cost_per_million_tokens=1.0, output_cost_per_million_tokens=2.0
        ),
        book_pricing=BookPricing(),
    )
    assert estimate.estimated is True
    assert estimate.words == 5
    assert estimate.characters == len("hello world") + len("another sentence here")
    assert estimate.pages == 1
    assert estimate.price == 7.0
    assert estimate.input_tokens >= 1
    assert estimate.output_tokens == estimate.input_tokens
    assert estimate.provider_cost > 0


def test_own_api_estimate_is_free_but_records_provider_cost() -> None:
    estimate = estimate_from_texts(
        ["hello world"],
        provider_pricing=ProviderPricing(input_cost_per_million_tokens=100.0),
        book_pricing=BookPricing(billing_mode=BillingMode.OWN_API.value),
    )
    assert estimate.price == 0.0
    assert estimate.provider_cost > 0


def test_more_than_one_block() -> None:
    # 300 words/page, 300,001 words -> 1001 pages -> two blocks.
    estimate = estimate_from_texts(
        ["word " * 300_001],
        provider_pricing=ProviderPricing(),
        book_pricing=BookPricing(),
    )
    assert estimate.pages == 1001
    assert estimate.price == 14.0


def test_empty_input() -> None:
    estimate = estimate_from_texts(
        [], provider_pricing=ProviderPricing(), book_pricing=BookPricing()
    )
    assert estimate.words == 0 and estimate.characters == 0 and estimate.price == 0.0
