"""Assemble application services for request handlers."""

from __future__ import annotations

from app.api.repositories import Repositories
from app.config import Settings
from app.documents.ingest import DocumentIngestService
from app.language.registry import PocketBaseLanguageRegistry
from app.providers.credentials import ProviderCredentialService
from app.providers.runtime import ProviderRuntime
from app.repositories.pocketbase import PocketBaseClient
from app.repositories.providers import (
    ProviderConnectionRepository,
    ProviderCredentialRepository,
    ProviderRepository,
)
from app.security.crypto import SecretCipher
from app.services.limits import LimitService
from app.settings.service import SettingsService
from app.storage.base import Storage
from app.translation.jobs_service import TranslationJobService
from app.translation.policy import TranslationPolicyService
from app.translation.policy_engine import TranslationPolicyEngine


def build_settings_service(repos: Repositories) -> SettingsService:
    return SettingsService(repos.settings)


def build_policy_engine(
    repos: Repositories, settings: SettingsService | None = None
) -> TranslationPolicyEngine:
    policy = TranslationPolicyService(
        profiles=repos.profiles,
        connections=repos.connections,
        models=repos.models,
        capabilities=repos.capabilities,
        templates=repos.prompt_templates,
        versions=repos.prompt_versions,
        settings=settings,
    )
    return TranslationPolicyEngine(
        policy_service=policy,
        languages=PocketBaseLanguageRegistry(repos.languages),
        models=repos.models,
        prompt_versions=repos.prompt_versions,
        settings=settings,
    )


def build_job_service(
    repos: Repositories, settings: SettingsService | None = None
) -> TranslationJobService:
    return TranslationJobService(
        jobs=repos.jobs,
        documents=repos.documents,
        policy=build_policy_engine(repos, settings),
        settings=settings,
    )


def build_ingest_service(
    repos: Repositories, storage: Storage, settings: Settings
) -> DocumentIngestService:
    return DocumentIngestService(repos.documents, storage, settings=settings)


def build_limit_service(
    repos: Repositories, settings: SettingsService | None, *, fallback_upload_bytes: int
) -> LimitService:
    return LimitService(
        documents=repos.documents,
        jobs=repos.jobs,
        settings=settings or build_settings_service(repos),
        fallback_upload_bytes=fallback_upload_bytes,
    )


def build_credential_service(
    client: PocketBaseClient, settings: Settings, *, token: str | None
) -> ProviderCredentialService:
    cipher = SecretCipher.from_secret(settings.encryption_key.get_secret_value())
    return ProviderCredentialService(
        ProviderCredentialRepository(client, token=token), cipher, token=token
    )


def build_provider_runtime(
    *,
    client: PocketBaseClient,
    settings: Settings,
    connections: ProviderConnectionRepository,
    providers: ProviderRepository,
    token: str | None,
    service_token: str | None,
) -> ProviderRuntime:
    return ProviderRuntime(
        connections=connections,
        providers=providers,
        credentials=build_credential_service(client, settings, token=service_token),
        token=token,
    )
