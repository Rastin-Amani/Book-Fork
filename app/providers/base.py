"""Translation provider abstraction.

The engine depends only on this contract; it never imports a vendor SDK or
assumes a specific API shape. Providers normalize messages, structured output,
usage and errors so the engine receives one consistent response.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ProviderSegment:
    id: str
    text: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    provider_cost: float | None = None
    estimated: bool = False
    latency_ms: float | None = None

    def merged(self, other: ProviderUsage) -> ProviderUsage:
        return ProviderUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            provider_cost=_add_optional(self.provider_cost, other.provider_cost),
            estimated=self.estimated or other.estimated,
            latency_ms=_add_optional(self.latency_ms, other.latency_ms),
        )


def _add_optional(left: float | None, right: float | None) -> float | None:
    if left is None:
        return right
    if right is None:
        return left
    return left + right


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    """A normalized, batch translation request."""

    segments: Sequence[ProviderSegment]
    user_prompt: str
    system_prompt: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None
    structured: bool = True
    response_schema: Mapping[str, Any] | None = None
    timeout_seconds: float | None = None
    params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    translations: Mapping[str, str] = field(default_factory=dict)
    content: str | None = None
    usage: ProviderUsage = field(default_factory=ProviderUsage)
    raw_metadata: Mapping[str, Any] = field(default_factory=dict)
    structured: bool = True


@runtime_checkable
class TranslationProvider(Protocol):
    """Executes translation for a single endpoint/model configuration."""

    name: str
    supports_structured_output: bool

    async def translate(self, request: ProviderRequest) -> ProviderResponse:
        """Translate the request's segments and return normalized results."""
        ...

    async def estimate_usage(self, request: ProviderRequest) -> ProviderUsage:
        """Estimate usage before execution (marked as an estimate)."""
        ...

    async def validate_connection(self) -> bool:
        """Whether the endpoint is reachable and credentials are accepted."""
        ...
