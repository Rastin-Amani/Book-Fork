"""Translation job service: plan building, estimation, creation."""

from __future__ import annotations

from app.language.registry import PocketBaseLanguageRegistry
from app.repositories.documents import DocumentRepository
from app.repositories.languages import LanguageRepository
from app.repositories.prompts import PromptTemplateRepository, PromptVersionRepository
from app.repositories.providers import (
    ModelCapabilityRepository,
    ProviderConnectionRepository,
    ProviderModelRepository,
)
from app.repositories.translation import (
    TranslationJobRepository,
    TranslationProfileRepository,
)
from app.schemas.documents import Document
from app.translation.jobs_service import TranslationJobService
from app.translation.policy import TranslationPolicyService
from app.translation.policy_engine import TranslationPolicyEngine


def _seed(fake_pb) -> None:
    fake_pb.seed(
        "languages",
        {
            "language_code": "en",
            "name": "English",
            "direction": "ltr",
            "script_code": "Latn",
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
            "billing_mode": "managed",
        },
    )
    model = fake_pb.seed(
        "provider_models",
        {
            "provider": provider["id"],
            "model_identifier": "m",
            "enabled": True,
            "quality_score": 0.9,
            "input_cost_per_million_tokens": 1.0,
            "output_cost_per_million_tokens": 2.0,
        },
    )
    fake_pb.seed(
        "model_capabilities",
        {"model": model["id"], "source_language": "en", "target_language": "fa", "supported": True},
    )
    template = fake_pb.seed(
        "prompt_templates",
        {"name": "T", "slug": "default-translation", "purpose": "translation", "enabled": True},
    )
    fake_pb.seed(
        "prompt_versions",
        {
            "template": template["id"],
            "version": 1,
            "status": "active",
            "body": (
                "Translate {{ source_language }} to {{ target_language }}.\n{{ source_segments }}"
            ),
        },
    )
    fake_pb.seed(
        "translation_profiles",
        {
            "name": "Default",
            "quality_mode": "balanced",
            "is_system_default": True,
            "enabled": True,
            "prompt_template": template["id"],
        },
    )


def _service(pb) -> TranslationJobService:
    policy = TranslationPolicyEngine(
        policy_service=TranslationPolicyService(
            profiles=TranslationProfileRepository(pb),
            connections=ProviderConnectionRepository(pb),
            models=ProviderModelRepository(pb),
            capabilities=ModelCapabilityRepository(pb),
            templates=PromptTemplateRepository(pb),
            versions=PromptVersionRepository(pb),
        ),
        languages=PocketBaseLanguageRegistry(LanguageRepository(pb)),
        models=ProviderModelRepository(pb),
        prompt_versions=PromptVersionRepository(pb),
    )
    return TranslationJobService(
        jobs=TranslationJobRepository(pb),
        documents=DocumentRepository(pb),
        policy=policy,
    )


def _document() -> Document:
    return Document(
        id="doc1",
        workspace="w1",
        original_filename="book.epub",
        status="ready",
        created_by="u1",
        document_type="epub",
        file_size=12000,
        storage_key="documents/doc1/source.epub",
    )


async def test_estimate_returns_credits_and_provider_cost(pb, fake_pb) -> None:
    _seed(fake_pb)
    service = _service(pb)
    plan = await service.build_plan(workspace_id="w1", source_language="en", target_language="fa")
    view = await service.estimate(document=_document(), plan=plan)
    assert view.billing_mode == "managed"
    assert view.model_identifier == "m"
    assert view.estimate.words > 0
    assert view.credits > 0
    assert view.provider_cost > 0


async def test_create_job_snapshots_plan(pb, fake_pb) -> None:
    _seed(fake_pb)
    service = _service(pb)
    plan = await service.build_plan(workspace_id="w1", source_language="en", target_language="fa")
    job = await service.create(workspace_id="w1", created_by="u1", document=_document(), plan=plan)
    assert job.status == "queued"
    assert job.snapshot and job.snapshot["target"]["direction"] == "rtl"
    assert job.model == plan.model_id
