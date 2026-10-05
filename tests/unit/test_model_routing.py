"""Cost-aware, capability-driven model routing by quality mode."""

from __future__ import annotations

from app.repositories.prompts import PromptTemplateRepository, PromptVersionRepository
from app.repositories.providers import (
    ModelCapabilityRepository,
    ProviderConnectionRepository,
    ProviderModelRepository,
)
from app.repositories.translation import TranslationProfileRepository
from app.schemas.translation import QualityMode
from app.translation.policy import TranslationPolicyRequest, TranslationPolicyService


def _service(pb) -> TranslationPolicyService:
    return TranslationPolicyService(
        profiles=TranslationProfileRepository(pb),
        connections=ProviderConnectionRepository(pb),
        models=ProviderModelRepository(pb),
        capabilities=ModelCapabilityRepository(pb),
        templates=PromptTemplateRepository(pb),
        versions=PromptVersionRepository(pb),
    )


def _seed(fake_pb) -> None:
    provider = fake_pb.seed(
        "providers",
        {
            "name": "P",
            "slug": "p",
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
            "name": "c",
            "auth_type": "api_key",
            "enabled": True,
        },
    )
    cheap = fake_pb.seed(
        "provider_models",
        {
            "provider": provider["id"],
            "model_identifier": "cheap",
            "enabled": True,
            "quality_score": 0.6,
            "input_cost_per_million_tokens": 0.1,
            "output_cost_per_million_tokens": 0.2,
        },
    )
    premium = fake_pb.seed(
        "provider_models",
        {
            "provider": provider["id"],
            "model_identifier": "premium",
            "enabled": True,
            "quality_score": 0.95,
            "input_cost_per_million_tokens": 10.0,
            "output_cost_per_million_tokens": 30.0,
        },
    )
    for model in (cheap, premium):
        fake_pb.seed(
            "model_capabilities",
            {
                "model": model["id"],
                "source_language": "en",
                "target_language": "fa",
                "supported": True,
            },
        )


async def _model_for(pb, mode: QualityMode) -> str | None:
    result = await _service(pb).resolve(
        TranslationPolicyRequest(
            source_language="en", target_language="fa", workspace_id="w1", quality_mode=mode
        )
    )
    return result.model


async def test_economy_prefers_cheaper_model(pb, fake_pb) -> None:
    _seed(fake_pb)
    model_id = await _model_for(pb, QualityMode.ECONOMY)
    model = await ProviderModelRepository(pb).get(model_id or "")
    assert model.model_identifier == "cheap"


async def test_best_prefers_higher_quality_model(pb, fake_pb) -> None:
    _seed(fake_pb)
    model_id = await _model_for(pb, QualityMode.BEST)
    model = await ProviderModelRepository(pb).get(model_id or "")
    assert model.model_identifier == "premium"


async def test_balanced_favours_quality(pb, fake_pb) -> None:
    _seed(fake_pb)
    model_id = await _model_for(pb, QualityMode.BALANCED)
    model = await ProviderModelRepository(pb).get(model_id or "")
    assert model.model_identifier == "premium"
