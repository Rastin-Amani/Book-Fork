"""Pre-translation usage estimation.

Everything returned is explicitly an estimate — never presented as exact.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.billing.pricing import (
    CreditPricing,
    CreditPricingEngine,
    ProviderPricing,
    ProviderPricingEngine,
)

_CHARS_PER_TOKEN = 4


@dataclass(frozen=True, slots=True)
class JobEstimate:
    words: int
    characters: int
    input_tokens: int
    output_tokens: int
    provider_cost: float
    credits: float
    estimated: bool = True


def estimate_from_texts(
    texts: Sequence[str],
    *,
    provider_pricing: ProviderPricing,
    credit_pricing: CreditPricing,
    output_ratio: float = 1.0,
) -> JobEstimate:
    characters = sum(len(text) for text in texts)
    words = sum(len(text.split()) for text in texts)
    return _estimate(
        characters=characters,
        words=words,
        provider_pricing=provider_pricing,
        credit_pricing=credit_pricing,
        output_ratio=output_ratio,
    )


def estimate_from_characters(
    characters: int,
    *,
    provider_pricing: ProviderPricing,
    credit_pricing: CreditPricing,
    words_per_character: float = 1 / 6,
    output_ratio: float = 1.0,
) -> JobEstimate:
    """Coarse estimate from raw byte/character count (marked estimated)."""
    return _estimate(
        characters=characters,
        words=int(characters * words_per_character),
        provider_pricing=provider_pricing,
        credit_pricing=credit_pricing,
        output_ratio=output_ratio,
    )


def _estimate(
    *,
    characters: int,
    words: int,
    provider_pricing: ProviderPricing,
    credit_pricing: CreditPricing,
    output_ratio: float,
) -> JobEstimate:
    input_tokens = max(1, characters // _CHARS_PER_TOKEN) if characters else 0
    output_tokens = int(input_tokens * output_ratio)
    provider_cost = ProviderPricingEngine().compute(
        provider_pricing, input_tokens=input_tokens, output_tokens=output_tokens
    )
    credits = CreditPricingEngine().compute(
        credit_pricing,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        provider_cost=provider_cost,
    )
    return JobEstimate(
        words=words,
        characters=characters,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        provider_cost=provider_cost,
        credits=credits,
    )
