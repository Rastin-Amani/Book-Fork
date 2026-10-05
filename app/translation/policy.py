"""Translation policy resolution.

Centralizes the "which provider/model/profile/prompt/segmentation/normalizer?"
decision behind one service boundary. It resolves from configuration records and
model capabilities — never from scattered ``if/elif`` checks in job code.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.repositories.prompts import PromptTemplateRepository, PromptVersionRepository
from app.repositories.providers import (
    ModelCapabilityRepository,
    ProviderConnectionRepository,
    ProviderModelRepository,
)
from app.repositories.translation import TranslationProfileRepository
from app.schemas.providers import ProviderModel
from app.schemas.translation import QualityMode, TranslationProfile

DEFAULT_PROMPT_SLUG_SETTING = "translation.default_prompt_template_slug"


@dataclass(frozen=True, slots=True)
class TranslationPolicyRequest:
    source_language: str
    target_language: str
    quality_mode: QualityMode | None = None
    workspace_id: str | None = None
    preferred_connection_id: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedTranslationPolicy:
    quality_mode: QualityMode
    profile: TranslationProfile | None = None
    provider_connection: str | None = None
    provider: str | None = None
    billing_mode: str = "managed"
    model: str | None = None
    prompt_template: str | None = None
    prompt_version: str | None = None
    temperature: float | None = None
    batch_size: int | None = None
    context_window_policy: Mapping[str, Any] = field(default_factory=dict)
    segmentation_strategy: Mapping[str, Any] = field(default_factory=dict)
    normalization_pipeline: Mapping[str, Any] = field(default_factory=dict)
    validation_profile: Mapping[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    def snapshot(self) -> dict[str, Any]:
        """Immutable config snapshot to persist on the translation job."""
        return {
            "quality_mode": self.quality_mode.value,
            "profile": self.profile.id if self.profile else None,
            "provider_connection": self.provider_connection,
            "provider": self.provider,
            "model": self.model,
            "prompt_template": self.prompt_template,
            "prompt_version": self.prompt_version,
            "temperature": self.temperature,
            "batch_size": self.batch_size,
            "context_window_policy": dict(self.context_window_policy),
            "segmentation_strategy": dict(self.segmentation_strategy),
            "normalization_pipeline": dict(self.normalization_pipeline),
            "validation_profile": dict(self.validation_profile),
            "reasons": list(self.reasons),
        }


class TranslationPolicyService:
    """Resolves a concrete, snapshot-able translation policy."""

    def __init__(
        self,
        *,
        profiles: TranslationProfileRepository,
        connections: ProviderConnectionRepository,
        models: ProviderModelRepository,
        capabilities: ModelCapabilityRepository,
        templates: PromptTemplateRepository,
        versions: PromptVersionRepository,
        settings: Any | None = None,
        token: str | None = None,
    ) -> None:
        self._profiles = profiles
        self._connections = connections
        self._models = models
        self._capabilities = capabilities
        self._templates = templates
        self._versions = versions
        self._settings = settings
        self._token = token

    async def resolve(self, request: TranslationPolicyRequest) -> ResolvedTranslationPolicy:
        reasons: list[str] = []
        profile = await self._select_profile(request)
        quality_mode = (
            request.quality_mode
            or (profile.quality_mode if profile else None)
            or QualityMode.BALANCED
        )
        if request.quality_mode:
            reasons.append("quality mode from request")
        elif profile:
            reasons.append("quality mode from profile")

        connection_id, provider_id = await self._select_connection(request)
        model_id = await self._select_model(request, connection_id, quality_mode)
        prompt_template, prompt_version = await self._select_prompt(profile)

        billing_mode = "managed"
        if connection_id:
            connection = await self._connections.get(connection_id, token=self._token)
            billing_mode = connection.billing_mode.value

        return ResolvedTranslationPolicy(
            quality_mode=quality_mode,
            profile=profile,
            provider_connection=connection_id,
            provider=provider_id,
            billing_mode=billing_mode,
            model=model_id,
            prompt_template=prompt_template,
            prompt_version=prompt_version,
            temperature=profile.temperature if profile else None,
            batch_size=profile.batch_size if profile else None,
            context_window_policy=dict(profile.context_window_policy) if profile else {},
            segmentation_strategy=dict(profile.segmentation_strategy) if profile else {},
            normalization_pipeline=dict(profile.normalization_pipeline) if profile else {},
            validation_profile=dict(profile.validation_profile) if profile else {},
            reasons=reasons,
        )

    async def _select_profile(self, request: TranslationPolicyRequest) -> TranslationProfile | None:
        profiles = await self._profiles.list_available(request.workspace_id, token=self._token)
        if not profiles:
            return None

        def rank(p: TranslationProfile) -> int:
            if p.source_language == request.source_language and p.target_language in (
                None,
                request.target_language,
            ):
                return 0
            if p.source_language is None and p.target_language in (
                None,
                request.target_language,
            ):
                return 1
            if p.is_system_default:
                return 2
            return 3

        return sorted(profiles, key=rank)[0]

    async def _select_connection(
        self, request: TranslationPolicyRequest
    ) -> tuple[str | None, str | None]:
        if request.preferred_connection_id:
            connection = await self._connections.get(
                request.preferred_connection_id, token=self._token
            )
            return connection.id, connection.provider
        if request.workspace_id:
            connections = await self._connections.list_for_workspace(
                request.workspace_id, token=self._token
            )
            enabled = [c for c in connections if c.enabled]
            if enabled:
                return enabled[0].id, enabled[0].provider
        return None, None

    async def _select_model(
        self,
        request: TranslationPolicyRequest,
        connection_id: str | None,
        quality_mode: QualityMode,
    ) -> str | None:
        capabilities = await self._capabilities.list_for_pair(
            request.source_language, request.target_language, token=self._token
        )
        supported = [c for c in capabilities if c.supported]
        if supported:
            scored: list[tuple[float, str]] = []
            for capability in supported:
                model = await self._models.get(capability.model, token=self._token)
                if not model.enabled:
                    continue
                quality = capability.quality_score or model.quality_score or 0.0
                score = _score_model(model, quality, quality_mode, preferred=capability.preferred)
                scored.append((score, model.id))
            if scored:
                scored.sort(reverse=True)
                return scored[0][1]
        if connection_id:
            connection = await self._connections.get(connection_id, token=self._token)
            models = await self._models.list_for_provider(connection.provider, token=self._token)
            enabled = [m for m in models if m.enabled]
            if enabled:
                scored2 = [
                    (_score_model(m, m.quality_score or 0.0, quality_mode, preferred=False), m.id)
                    for m in enabled
                ]
                scored2.sort(reverse=True)
                return scored2[0][1]
        return None

    async def _select_prompt(
        self, profile: TranslationProfile | None
    ) -> tuple[str | None, str | None]:
        template_id = profile.prompt_template if profile else None
        if template_id is None and self._settings is not None:
            slug = await self._settings.get(DEFAULT_PROMPT_SLUG_SETTING)
            if slug:
                template = await self._templates.get_by_slug(slug, token=self._token)
                template_id = template.id if template else None
        if template_id is None:
            return None, None
        version = await self._versions.get_active(template_id, token=self._token)
        return template_id, (version.id if version else None)


def _score_model(
    model: ProviderModel, quality: float, mode: QualityMode, *, preferred: bool
) -> float:
    """Mode-aware ranking; no model name is embedded in a quality tier."""
    cost = float(model.input_cost_per_million_tokens or 0.0) + float(
        model.output_cost_per_million_tokens or 0.0
    )
    if mode in (QualityMode.ECONOMY, QualityMode.FAST):
        score = -cost + quality * 0.001
    elif mode is QualityMode.BEST:
        score = quality * 1000.0 - cost * 0.001
    else:  # balanced / quality
        score = quality * 100.0 - cost * 0.01
    if preferred:
        score += 1_000_000.0
    return score
