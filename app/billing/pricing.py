"""Provider-cost and book-order pricing engines.

Formulas live here, not scattered through the worker. Provider cost is computed
from model pricing and kept internal for margin monitoring. Customers buy books,
not tokens: one managed job is one flat-priced order, split into 1,000-page
blocks. Own-API jobs are free.
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
class BookPricing:
    billing_mode: str = BillingMode.MANAGED.value
    price_per_book: float = 7.0
    pages_per_block: int = 1000
    words_per_page: int = 300
    currency: str = "USD"


@dataclass(frozen=True, slots=True)
class BookQuote:
    pages: int
    blocks: int
    price: float
    currency: str


class BookPricingEngine:
    """Turns an estimated page count into a flat per-book order price."""

    def quote(self, pricing: BookPricing, *, pages: int) -> BookQuote:
        pages = max(0, int(pages))
        if pricing.billing_mode == BillingMode.OWN_API.value or pages == 0:
            return BookQuote(pages=pages, blocks=0, price=0.0, currency=pricing.currency)
        block_size = max(1, pricing.pages_per_block)
        blocks = -(-pages // block_size)
        return BookQuote(
            pages=pages,
            blocks=blocks,
            price=round(blocks * max(0.0, pricing.price_per_book), 2),
            currency=pricing.currency,
        )
