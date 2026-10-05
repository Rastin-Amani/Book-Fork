"""Generic provider-cost and Book Fork-credit pricing engines.

Formulas live here, not scattered through the worker. Provider cost is computed
from model pricing; Book Fork credits are a product abstraction derived from tokens
and/or provider cost according to the connection's billing mode. Own-API mode
consumes zero Book Fork credits.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.providers import BillingMode, ProviderModel


@dataclass(frozen=True, slots=True)
class ProviderPricing:
    input_cost_per_million_tokens: float = 0.0
    output_cost_per_million_tokens: float = 0.0
    request_cost: float = 0.0

    @classmethod
    def from_model(cls, model: ProviderModel) -> ProviderPricing:
        return cls(
            input_cost_per_million_tokens=float(model.input_cost_per_million_tokens or 0.0),
            output_cost_per_million_tokens=float(model.output_cost_per_million_tokens or 0.0),
            request_cost=float(model.request_cost or 0.0),
        )


class ProviderPricingEngine:
    """Turns token usage into provider cost."""

    def compute(
        self,
        pricing: ProviderPricing,
        *,
        input_tokens: int,
        output_tokens: int,
        requests: int = 1,
    ) -> float:
        return (
            input_tokens / 1_000_000 * pricing.input_cost_per_million_tokens
            + output_tokens / 1_000_000 * pricing.output_cost_per_million_tokens
            + requests * pricing.request_cost
        )


@dataclass(frozen=True, slots=True)
class CreditPricing:
    billing_mode: str = BillingMode.MANAGED.value
    credits_per_1000_tokens: float = 1.0
    provider_cost_markup: float = 0.0
    currency: str = "credits"


class CreditPricingEngine:
    """Turns usage/provider cost into Book Fork credits."""

    def compute(
        self,
        pricing: CreditPricing,
        *,
        input_tokens: int,
        output_tokens: int,
        provider_cost: float = 0.0,
    ) -> float:
        if pricing.billing_mode == BillingMode.OWN_API.value:
            return 0.0  # own-API mode consumes no Book Fork credits
        tokens = input_tokens + output_tokens
        return (
            tokens / 1000.0 * pricing.credits_per_1000_tokens
            + provider_cost * pricing.provider_cost_markup
        )
