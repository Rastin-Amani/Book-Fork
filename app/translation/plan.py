"""Typed, immutable translation plan.

A plan is the resolved snapshot a job executes against. Once built, execution
never re-queries mutable settings — the plan carries every decision needed to
reproduce the translation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from app.providers.errors import ProviderErrorCategory

DEFAULT_RETRY_CATEGORIES = frozenset(
    {
        ProviderErrorCategory.RATE_LIMITED,
        ProviderErrorCategory.TIMEOUT,
        ProviderErrorCategory.UNAVAILABLE,
        ProviderErrorCategory.UNKNOWN,
    }
)


@dataclass(frozen=True, slots=True)
class LanguageSpec:
    tag: str
    locale: str | None = None
    script: str | None = None
    direction: str = "ltr"
    name: str | None = None


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 8.0
    retry_categories: frozenset[ProviderErrorCategory] = DEFAULT_RETRY_CATEGORIES


@dataclass(frozen=True, slots=True)
class ContextPolicy:
    strategy: str = "adaptive"
    max_previous_segments: int = 3
    max_context_tokens: int = 2000
    max_glossary_terms: int = 50


@dataclass(frozen=True, slots=True)
class FallbackPolicy:
    """Direct translation is preferred; pivot is a last resort and opt-in."""

    strategy: str = "direct"  # direct | fallback_model | fallback_provider | optional_pivot
    fallback_model_id: str | None = None
    fallback_provider_connection_id: str | None = None
    pivot_language: str | None = None


@dataclass(frozen=True, slots=True)
class UsageEstimate:
    input_tokens: int = 0
    output_tokens: int = 0
    words: int = 0
    characters: int = 0
    pages: int = 0
    blocks: int = 0
    price: float = 0.0
    currency: str = "USD"
    provider_cost: float | None = None
    estimated: bool = True


@dataclass(frozen=True, slots=True)
class TranslationPlan:
    source: LanguageSpec
    target: LanguageSpec
    # -- resolved configuration ---------------------------------------------
    quality_mode: str | None = None
    profile_id: str | None = None
    profile_snapshot: Mapping[str, Any] = field(default_factory=dict)
    provider_id: str | None = None
    provider_type: str | None = None
    provider_connection_id: str | None = None
    model_id: str | None = None
    model_identifier: str | None = None
    prompt_template_id: str | None = None
    prompt_version_id: str | None = None
    prompt_body: str | None = None
    segmentation_strategy: str = "structure_aware"
    context_policy: ContextPolicy = field(default_factory=ContextPolicy)
    normalization_pipeline: Mapping[str, Any] = field(default_factory=dict)
    validation_profile: Mapping[str, Any] = field(default_factory=dict)
    # -- execution parameters ------------------------------------------------
    batch_size: int = 20
    temperature: float | None = None
    max_output_tokens: int | None = None
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    fallback: FallbackPolicy = field(default_factory=FallbackPolicy)
    billing_mode: str = "managed"
    pricing: Mapping[str, Any] = field(default_factory=dict)
    expected_usage: UsageEstimate | None = None
    reasons: Sequence[str] = field(default_factory=tuple)

    def snapshot(self) -> dict[str, Any]:
        """A JSON-serializable, reproducible snapshot for the job record."""
        return {
            "source": asdict(self.source),
            "target": asdict(self.target),
            "quality_mode": self.quality_mode,
            "profile_id": self.profile_id,
            "profile_snapshot": dict(self.profile_snapshot),
            "provider_id": self.provider_id,
            "provider_type": self.provider_type,
            "provider_connection_id": self.provider_connection_id,
            "model_id": self.model_id,
            "model_identifier": self.model_identifier,
            "prompt_template_id": self.prompt_template_id,
            "prompt_version_id": self.prompt_version_id,
            "prompt_body": self.prompt_body,
            "segmentation_strategy": self.segmentation_strategy,
            "context_policy": asdict(self.context_policy),
            "normalization_pipeline": dict(self.normalization_pipeline),
            "validation_profile": dict(self.validation_profile),
            "batch_size": self.batch_size,
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
            "retry_policy": {
                "max_attempts": self.retry_policy.max_attempts,
                "base_delay_seconds": self.retry_policy.base_delay_seconds,
                "max_delay_seconds": self.retry_policy.max_delay_seconds,
                "retry_categories": sorted(str(c) for c in self.retry_policy.retry_categories),
            },
            "fallback": asdict(self.fallback),
            "billing_mode": self.billing_mode,
            "pricing": dict(self.pricing),
            "expected_usage": asdict(self.expected_usage) if self.expected_usage else None,
            "reasons": list(self.reasons),
        }

    @classmethod
    def from_snapshot(cls, data: Mapping[str, Any]) -> TranslationPlan:
        """Reconstruct a plan from a persisted snapshot (worker resume)."""
        retry_data = data.get("retry_policy") or {}
        categories = retry_data.get("retry_categories")
        retry_categories = (
            frozenset(ProviderErrorCategory(value) for value in categories)
            if categories
            else DEFAULT_RETRY_CATEGORIES
        )
        usage = data.get("expected_usage")
        usage_data = dict(usage) if usage else {}
        usage_data.pop("credits", None)  # pre-v3 snapshots
        return cls(
            source=LanguageSpec(**data["source"]),
            target=LanguageSpec(**data["target"]),
            quality_mode=data.get("quality_mode"),
            profile_id=data.get("profile_id"),
            profile_snapshot=data.get("profile_snapshot") or {},
            provider_id=data.get("provider_id"),
            provider_type=data.get("provider_type"),
            provider_connection_id=data.get("provider_connection_id"),
            model_id=data.get("model_id"),
            model_identifier=data.get("model_identifier"),
            prompt_template_id=data.get("prompt_template_id"),
            prompt_version_id=data.get("prompt_version_id"),
            prompt_body=data.get("prompt_body"),
            segmentation_strategy=data.get("segmentation_strategy", "structure_aware"),
            context_policy=ContextPolicy(**(data.get("context_policy") or {})),
            normalization_pipeline=data.get("normalization_pipeline") or {},
            validation_profile=data.get("validation_profile") or {},
            batch_size=int(data.get("batch_size", 20)),
            temperature=data.get("temperature"),
            max_output_tokens=data.get("max_output_tokens"),
            retry_policy=RetryPolicy(
                max_attempts=int(retry_data.get("max_attempts", 3)),
                base_delay_seconds=float(retry_data.get("base_delay_seconds", 0.5)),
                max_delay_seconds=float(retry_data.get("max_delay_seconds", 8.0)),
                retry_categories=retry_categories,
            ),
            fallback=FallbackPolicy(**(data.get("fallback") or {})),
            billing_mode=str(data.get("billing_mode", "managed")),
            pricing=data.get("pricing") or {},
            expected_usage=UsageEstimate(**usage_data) if usage_data else None,
            reasons=tuple(data.get("reasons") or ()),
        )
