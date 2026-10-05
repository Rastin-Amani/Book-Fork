"""Translation policy engine: plan resolution and reproducibility."""

from __future__ import annotations

import json

import pytest
from app.exceptions import ConfigurationError
from app.language.registry import PocketBaseLanguageRegistry
from app.repositories.languages import LanguageRepository
from app.repositories.prompts import PromptTemplateRepository, PromptVersionRepository
from app.repositories.providers import (
    ModelCapabilityRepository,
    ProviderConnectionRepository,
    ProviderModelRepository,
)
from app.repositories.settings import SystemSettingRepository
from app.repositories.translation import TranslationProfileRepository
from app.settings.service import SettingsService
from app.translation.policy import TranslationPolicyService
from app.translation.policy_engine import PlanRequest, TranslationPolicyEngine

from tests.translation_fixtures import FakeProvider


def _seed(fake_pb) -> None:
    fake_pb.seed(
        "languages",
        {
            "language_code": "en",
            "name": "English",
            "direction": "ltr",
            "script_code": "Latn",
            "default_locale": "en",
            "enabled": True,
        },
    )
    fake_pb.seed(
        "languages",
        {
            "language_code": "fa",
            "name": "Persian",
            "direction": "rtl",
            "script_code": "Arab",
            "default_locale": "fa-IR",
            "enabled": True,
        },
    )
    provider = fake_pb.seed(
        "providers",
        {
            "name": "OpenAI-compatible",
            "slug": "openai-compatible",
            "provider_type": "openai_compatible",
            "authentication_type": "api_key",
            "enabled": True,
        },
    )
    fake_pb.seed(
        "provider_connections",
        {
            "workspace": "w1",
            "provider": provider["id"],
            "name": "main",
            "auth_type": "api_key",
            "enabled": True,
        },
    )
    model = fake_pb.seed(
        "provider_models",
        {
            "provider": provider["id"],
            "model_identifier": "gpt-x",
            "enabled": True,
            "quality_score": 0.9,
        },
    )
    fake_pb.seed(
        "model_capabilities",
        {
            "model": model["id"],
            "source_language": "en",
            "target_language": "fa",
            "supported": True,
            "preferred": True,
        },
    )
    template = fake_pb.seed(
        "prompt_templates",
        {
            "name": "Default Translation",
            "slug": "default-translation",
            "purpose": "translation",
            "enabled": True,
        },
    )
    fake_pb.seed(
        "prompt_versions",
        {
            "template": template["id"],
            "version": 1,
            "status": "active",
            "body": (
                "Translate {{ source_language }} into {{ target_language }}.\n{{ source_segments }}"
            ),
        },
    )
    fake_pb.seed(
        "translation_profiles",
        {
            "name": "Default Translation",
            "quality_mode": "balanced",
            "is_system_default": True,
            "enabled": True,
            "prompt_template": template["id"],
            "batch_size": 20,
            "temperature": 0.3,
            "segmentation_strategy": {"type": "sentence"},
            "context_strategy": {"strategy": "previous_segments", "max_previous_segments": 2},
            "normalization_pipeline": {"steps": ["unicode_nfkc"]},
        },
    )
    fake_pb.seed(
        "system_settings",
        {
            "key": "translation.default_prompt_template_slug",
            "value": "default-translation",
            "type": "string",
        },
    )


def _engine(pb, settings=None) -> TranslationPolicyEngine:
    policy = TranslationPolicyService(
        profiles=TranslationProfileRepository(pb),
        connections=ProviderConnectionRepository(pb),
        models=ProviderModelRepository(pb),
        capabilities=ModelCapabilityRepository(pb),
        templates=PromptTemplateRepository(pb),
        versions=PromptVersionRepository(pb),
        settings=settings,
    )
    return TranslationPolicyEngine(
        policy_service=policy,
        languages=PocketBaseLanguageRegistry(LanguageRepository(pb)),
        models=ProviderModelRepository(pb),
        prompt_versions=PromptVersionRepository(pb),
        settings=settings,
        provider=FakeProvider(),
    )


async def test_builds_reproducible_plan(pb, fake_pb) -> None:
    _seed(fake_pb)
    engine = _engine(pb)
    request = PlanRequest(source_language="en", target_language="fa", workspace_id="w1")
    plan = await engine.build_plan(request, segments=["Hello", "World"])

    assert plan.source.direction == "ltr"
    assert plan.target.direction == "rtl"
    assert plan.target.script == "Arab"
    assert plan.target.locale == "fa-IR"
    assert plan.model_identifier == "gpt-x"
    assert plan.quality_mode == "balanced"
    assert plan.prompt_body is not None and "Translate" in plan.prompt_body
    assert plan.batch_size == 20
    assert plan.temperature == 0.3
    assert plan.segmentation_strategy == "sentence"
    assert plan.context_policy.strategy == "previous_segments"
    assert plan.context_policy.max_previous_segments == 2
    assert plan.normalization_pipeline == {"steps": ["unicode_nfkc"]}
    assert plan.expected_usage is not None and plan.expected_usage.estimated is True

    # Reproducible and JSON-serializable snapshot.
    again = await engine.build_plan(request, segments=["Hello", "World"])
    assert plan.snapshot() == again.snapshot()
    json.dumps(plan.snapshot())


async def test_unknown_language_rejected(pb, fake_pb) -> None:
    _seed(fake_pb)
    with pytest.raises(ConfigurationError):
        await _engine(pb).build_plan(PlanRequest(source_language="zz", target_language="fa"))


async def test_settings_override_retry(pb, fake_pb) -> None:
    _seed(fake_pb)
    fake_pb.seed(
        "system_settings", {"key": "translation.retry.max_attempts", "value": 7, "type": "int"}
    )
    settings = SettingsService(SystemSettingRepository(pb))
    plan = await _engine(pb, settings).build_plan(
        PlanRequest(source_language="en", target_language="fa", workspace_id="w1")
    )
    assert plan.retry_policy.max_attempts == 7
