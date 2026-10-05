"""Translation policy resolution from configuration and capabilities."""

from __future__ import annotations

from typing import Any

from app.repositories.prompts import PromptTemplateRepository, PromptVersionRepository
from app.repositories.providers import (
    ModelCapabilityRepository,
    ProviderConnectionRepository,
    ProviderModelRepository,
)
from app.repositories.translation import TranslationProfileRepository
from app.schemas.translation import QualityMode
from app.translation.policy import TranslationPolicyRequest, TranslationPolicyService


class _StubSettings:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    async def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)


def _service(pb, settings: Any = None) -> TranslationPolicyService:
    return TranslationPolicyService(
        profiles=TranslationProfileRepository(pb),
        connections=ProviderConnectionRepository(pb),
        models=ProviderModelRepository(pb),
        capabilities=ModelCapabilityRepository(pb),
        templates=PromptTemplateRepository(pb),
        versions=PromptVersionRepository(pb),
        settings=settings,
    )


def _seed(pb, fake_pb):
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
    ws = fake_pb.seed("workspaces", {"name": "W", "slug": "w", "owner": "u1"})
    connection = fake_pb.seed(
        "provider_connections",
        {
            "workspace": ws["id"],
            "provider": provider["id"],
            "name": "main",
            "auth_type": "api_key",
            "enabled": True,
        },
    )
    weak = fake_pb.seed(
        "provider_models",
        {
            "provider": provider["id"],
            "model_identifier": "weak",
            "enabled": True,
            "quality_score": 0.4,
        },
    )
    strong = fake_pb.seed(
        "provider_models",
        {
            "provider": provider["id"],
            "model_identifier": "strong",
            "enabled": True,
            "quality_score": 0.9,
        },
    )
    fake_pb.seed(
        "model_capabilities",
        {
            "model": strong["id"],
            "source_language": "en",
            "target_language": "de",
            "supported": True,
            "preferred": True,
            "quality_score": 0.8,
        },
    )
    fake_pb.seed(
        "model_capabilities",
        {
            "model": weak["id"],
            "source_language": "en",
            "target_language": "de",
            "supported": True,
            "quality_score": 0.9,
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
            "body": "Translate {{ source_language }}",
            "status": "active",
        },
    )
    fake_pb.seed(
        "translation_profiles",
        {
            "name": "Default Translation",
            "quality_mode": "balanced",
            "is_system_default": True,
            "enabled": True,
        },
    )
    return ws, strong, connection


async def test_capability_preferred_model_and_prompt(pb, fake_pb) -> None:
    ws, strong, connection = _seed(pb, fake_pb)
    settings = _StubSettings({"translation.default_prompt_template_slug": "default-translation"})
    policy = await _service(pb, settings).resolve(
        TranslationPolicyRequest(source_language="en", target_language="de", workspace_id=ws["id"])
    )
    assert policy.model == strong["id"]  # preferred capability wins over raw score
    assert policy.provider_connection == connection["id"]
    assert policy.quality_mode is QualityMode.BALANCED
    assert policy.prompt_version is not None
    assert policy.snapshot()["model"] == strong["id"]


async def test_fallback_to_best_model_without_capability(pb, fake_pb) -> None:
    ws, _strong, _connection = _seed(pb, fake_pb)
    policy = await _service(pb).resolve(
        TranslationPolicyRequest(source_language="en", target_language="fr", workspace_id=ws["id"])
    )
    # No capability for en->fr: fall back to the highest-quality enabled model.
    from app.repositories.providers import ProviderModelRepository

    assert policy.model is not None
    model = await ProviderModelRepository(pb).get(policy.model)
    assert model.model_identifier == "strong"


async def test_quality_mode_override(pb, fake_pb) -> None:
    ws, _strong, _connection = _seed(pb, fake_pb)
    policy = await _service(pb).resolve(
        TranslationPolicyRequest(
            source_language="en",
            target_language="de",
            workspace_id=ws["id"],
            quality_mode=QualityMode.BEST,
        )
    )
    assert policy.quality_mode is QualityMode.BEST
    assert any("request" in reason for reason in policy.reasons)


async def test_no_config_resolves_empty_policy(pb) -> None:
    policy = await _service(pb).resolve(
        TranslationPolicyRequest(source_language="en", target_language="de")
    )
    assert policy.model is None
    assert policy.provider_connection is None
