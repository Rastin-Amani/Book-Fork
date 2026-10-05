"""Translation policy engine.

Turns a request into a fully resolved, reproducible :class:`TranslationPlan`.
It validates the language pair and provider/model capability, respects a
user-selected connection and the quality mode, selects profile/model/prompt/
normalization/validation, and estimates usage. This is the only place routing
decisions are made — the worker never contains them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from app.billing.estimation import estimate_from_texts
from app.billing.pricing import CreditPricing, ProviderPricing
from app.exceptions import ConfigurationError
from app.language.models import Direction, Language
from app.language.registry import PocketBaseLanguageRegistry
from app.repositories.prompts import PromptVersionRepository
from app.repositories.providers import ProviderModelRepository
from app.settings.service import SettingsService
from app.translation.plan import (
    ContextPolicy,
    CreditPolicy,
    FallbackPolicy,
    LanguageSpec,
    RetryPolicy,
    TranslationPlan,
    UsageEstimate,
)
from app.translation.policy import TranslationPolicyRequest, TranslationPolicyService

# Setting keys (business defaults live in the database, not here).
KEY_RETRY_MAX = "translation.retry.max_attempts"
KEY_RETRY_BASE = "translation.retry.base_delay_seconds"
KEY_RETRY_MAX_DELAY = "translation.retry.max_delay_seconds"
KEY_CONTEXT_STRATEGY = "translation.context.strategy"
KEY_CONTEXT_PREVIOUS = "translation.context.max_previous_segments"
KEY_CONTEXT_TOKENS = "translation.context.max_context_tokens"
KEY_GLOSSARY_TERMS = "translation.context.max_glossary_terms"
KEY_DEFAULT_BATCH = "translation.default_batch_size"
KEY_RESERVATION_MULTIPLIER = "billing.credit_reservation_multiplier"
KEY_FALLBACK_STRATEGY = "translation.fallback.strategy"
KEY_MAX_OUTPUT_TOKENS = "translation.max_output_tokens"
KEY_CREDITS_PER_1K = "billing.credits_per_1000_tokens"
KEY_PROVIDER_MARKUP = "billing.provider_cost_markup"
KEY_CURRENCY = "billing.default_currency"

_DEFAULTS: dict[str, Any] = {
    KEY_RETRY_MAX: 3,
    KEY_RETRY_BASE: 0.5,
    KEY_RETRY_MAX_DELAY: 8.0,
    KEY_CONTEXT_STRATEGY: "adaptive",
    KEY_CONTEXT_PREVIOUS: 3,
    KEY_CONTEXT_TOKENS: 2000,
    KEY_GLOSSARY_TERMS: 50,
    KEY_DEFAULT_BATCH: 20,
    KEY_RESERVATION_MULTIPLIER: 1.2,
    KEY_FALLBACK_STRATEGY: "direct",
    KEY_MAX_OUTPUT_TOKENS: None,
    KEY_CREDITS_PER_1K: 1.0,
    KEY_PROVIDER_MARKUP: 0.0,
    KEY_CURRENCY: "credits",
}


@dataclass(frozen=True, slots=True)
class PlanRequest:
    source_language: str
    target_language: str
    workspace_id: str | None = None
    source_locale: str | None = None
    target_locale: str | None = None
    quality_mode: str | None = None
    provider_connection_id: str | None = None
    profile_id: str | None = None
    user_instructions: str | None = None


class TranslationPolicyEngine:
    def __init__(
        self,
        *,
        policy_service: TranslationPolicyService,
        languages: PocketBaseLanguageRegistry,
        models: ProviderModelRepository,
        prompt_versions: PromptVersionRepository,
        settings: SettingsService | None = None,
        provider: Any | None = None,
    ) -> None:
        self._policy = policy_service
        self._languages = languages
        self._models = models
        self._prompt_versions = prompt_versions
        self._settings = settings
        self._provider = provider

    async def build_plan(
        self, request: PlanRequest, *, segments: Sequence[str] = ()
    ) -> TranslationPlan:
        source = await self._languages.resolve(request.source_language)
        target = await self._languages.resolve(request.target_language)
        if source is None:
            raise ConfigurationError(f"Unknown source language {request.source_language!r}.")
        if target is None:
            raise ConfigurationError(f"Unknown target language {request.target_language!r}.")

        reasons: list[str] = []
        if source.iso639_1 == target.iso639_1 and source.tag == target.tag:
            reasons.append("source and target languages are identical")

        quality = request.quality_mode
        resolved = await self._policy.resolve(
            TranslationPolicyRequest(
                source_language=source.iso639_1 or source.tag,
                target_language=target.iso639_1 or target.tag,
                quality_mode=_quality(quality),
                workspace_id=request.workspace_id,
                preferred_connection_id=request.provider_connection_id,
            )
        )
        reasons.extend(resolved.reasons)

        model_identifier = None
        provider_pricing = ProviderPricing()
        if resolved.model:
            model = await self._models.get(resolved.model)
            model_identifier = model.model_identifier
            provider_pricing = ProviderPricing.from_model(model)
            if not model.enabled:
                raise ConfigurationError("The selected model is disabled.")

        prompt_body = None
        if resolved.prompt_version:
            version = await self._prompt_versions.get(resolved.prompt_version)
            prompt_body = version.body

        profile_snapshot = resolved.profile.model_dump(mode="json") if resolved.profile else {}

        context_policy = await self._build_context_policy(profile_snapshot)
        retry_policy = await self._build_retry_policy()
        credit_policy = CreditPolicy(
            reservation_multiplier=float(await self._setting(KEY_RESERVATION_MULTIPLIER))
        )
        fallback = FallbackPolicy(
            strategy=str(await self._setting(KEY_FALLBACK_STRATEGY)),
        )
        batch_size = int(
            profile_snapshot.get("batch_size") or await self._setting(KEY_DEFAULT_BATCH)
        )
        segmentation = str(
            (profile_snapshot.get("segmentation_strategy") or {}).get("type") or "structure_aware"
        )
        normalization = profile_snapshot.get("normalization_pipeline") or {}
        validation_profile = profile_snapshot.get("validation_profile") or {}

        plan = TranslationPlan(
            source=_language_spec(source, request.source_locale),
            target=_language_spec(target, request.target_locale),
            quality_mode=resolved.quality_mode.value,
            profile_id=resolved.profile.id if resolved.profile else None,
            profile_snapshot=profile_snapshot,
            provider_id=resolved.provider,
            provider_type=None,
            provider_connection_id=resolved.provider_connection,
            model_id=resolved.model,
            model_identifier=model_identifier,
            prompt_template_id=resolved.prompt_template,
            prompt_version_id=resolved.prompt_version,
            prompt_body=prompt_body,
            segmentation_strategy=segmentation,
            context_policy=context_policy,
            normalization_pipeline=normalization,
            validation_profile=validation_profile,
            batch_size=max(1, batch_size),
            temperature=profile_snapshot.get("temperature"),
            max_output_tokens=await self._setting(KEY_MAX_OUTPUT_TOKENS),
            retry_policy=retry_policy,
            credit_policy=credit_policy,
            fallback=fallback,
            billing_mode=resolved.billing_mode,
            pricing=asdict(provider_pricing),
            expected_usage=await self._estimate_usage(
                plan_inputs=segments,
                provider_pricing=provider_pricing,
                billing_mode=resolved.billing_mode,
            ),
            reasons=tuple(reasons),
        )
        return plan

    async def _estimate_usage(
        self,
        *,
        plan_inputs: Sequence[str],
        provider_pricing: ProviderPricing,
        billing_mode: str,
    ) -> UsageEstimate | None:
        if not plan_inputs:
            return None
        credit_pricing = CreditPricing(
            billing_mode=billing_mode,
            credits_per_1000_tokens=float(await self._setting(KEY_CREDITS_PER_1K)),
            provider_cost_markup=float(await self._setting(KEY_PROVIDER_MARKUP)),
            currency=str(await self._setting(KEY_CURRENCY)),
        )
        estimate = estimate_from_texts(
            list(plan_inputs),
            provider_pricing=provider_pricing,
            credit_pricing=credit_pricing,
        )
        return UsageEstimate(
            input_tokens=estimate.input_tokens,
            output_tokens=estimate.output_tokens,
            words=estimate.words,
            characters=estimate.characters,
            provider_cost=estimate.provider_cost,
            credits=estimate.credits,
            estimated=True,
        )

    async def _build_context_policy(self, profile: Mapping[str, Any]) -> ContextPolicy:
        profile_context = profile.get("context_strategy") or {}
        strategy = str(profile_context.get("strategy") or await self._setting(KEY_CONTEXT_STRATEGY))
        return ContextPolicy(
            strategy=strategy,
            max_previous_segments=int(
                profile_context.get("max_previous_segments")
                or await self._setting(KEY_CONTEXT_PREVIOUS)
            ),
            max_context_tokens=int(
                profile_context.get("max_context_tokens") or await self._setting(KEY_CONTEXT_TOKENS)
            ),
            max_glossary_terms=int(
                profile_context.get("max_glossary_terms") or await self._setting(KEY_GLOSSARY_TERMS)
            ),
        )

    async def _build_retry_policy(self) -> RetryPolicy:
        return RetryPolicy(
            max_attempts=int(await self._setting(KEY_RETRY_MAX)),
            base_delay_seconds=float(await self._setting(KEY_RETRY_BASE)),
            max_delay_seconds=float(await self._setting(KEY_RETRY_MAX_DELAY)),
        )

    async def _setting(self, key: str) -> Any:
        if self._settings is None:
            return _DEFAULTS.get(key)
        return await self._settings.get(key, _DEFAULTS.get(key))


def _language_spec(language: Language, locale: str | None) -> LanguageSpec:
    return LanguageSpec(
        tag=language.tag,
        locale=locale or language.metadata.get("default_locale") or language.tag,
        script=language.script,
        direction="rtl" if language.direction is Direction.RTL else "ltr",
        name=language.name,
    )


def _quality(value: str | None) -> Any:
    if not value:
        return None
    from app.schemas.translation import QualityMode

    try:
        return QualityMode(value)
    except ValueError as exc:
        raise ConfigurationError(f"Unknown quality mode {value!r}.") from exc
