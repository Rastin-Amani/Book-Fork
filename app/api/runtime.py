"""Assemble application services for request handlers."""

from __future__ import annotations

from app.api.repositories import Repositories, build_repositories
from app.billing.service import BillingService
from app.config import Settings
from app.context import AppContext
from app.documents.ingest import DocumentIngestService
from app.exceptions import ConfigurationError
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


async def build_billing_service(
    ctx: AppContext,
    repos: Repositories,
    settings: SettingsService | None = None,
) -> BillingService:
    """Build the billing service with trusted write access.

    Billing mutations must not rely on client-writable collection rules, so they
    use the PocketBase service credential. Refuse to run an enabled billing
    server without it rather than falling back to a permissive path.
    """
    token = await ctx.ensure_service_token()
    if ctx.settings.billing_enabled and token is None:
        raise ConfigurationError(
            "Billing requires POCKETBASE_SERVICE_CREDENTIAL for trusted invoice writes."
        )
    writes = repos if token is None else build_repositories(ctx.pocketbase, token=token)
    return BillingService(
        invoices=writes.invoices,
        events=writes.billing_events,
        claims=writes.billing_claims,
        jobs=writes.jobs,
        settings=settings or build_settings_service(writes),
        provider=ctx.payments,
        billing_enabled=ctx.settings.billing_enabled,
    )


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
