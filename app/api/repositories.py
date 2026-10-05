"""Per-request repository bundle.

Constructed with the requesting user's token so PocketBase rules apply to every
query. The web layer never builds raw PocketBase calls inline.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.repositories.billing import (
    CreditTransactionRepository,
    CreditWalletRepository,
    UsageEventRepository,
)
from app.repositories.documents import DocumentRepository, DocumentSectionRepository
from app.repositories.knowledge import (
    GlossaryRepository,
    GlossaryTermRepository,
    TranslationMemoryRepository,
)
from app.repositories.languages import LanguageRepository, LanguageVariantRepository
from app.repositories.pocketbase import PocketBaseClient
from app.repositories.prompts import PromptTemplateRepository, PromptVersionRepository
from app.repositories.providers import (
    ModelCapabilityRepository,
    ProviderConnectionRepository,
    ProviderCredentialRepository,
    ProviderModelRepository,
    ProviderRepository,
)
from app.repositories.settings import SystemSettingRepository
from app.repositories.translation import (
    JobEventRepository,
    TranslationAttemptRepository,
    TranslationJobRepository,
    TranslationProfileRepository,
    TranslationSegmentRepository,
)
from app.repositories.workers import UserRepository, WorkerRepository
from app.repositories.workspaces import WorkspaceMemberRepository, WorkspaceRepository


@dataclass(slots=True)
class Repositories:
    workspaces: WorkspaceRepository
    workspace_members: WorkspaceMemberRepository
    documents: DocumentRepository
    document_sections: DocumentSectionRepository
    jobs: TranslationJobRepository
    segments: TranslationSegmentRepository
    attempts: TranslationAttemptRepository
    job_events: JobEventRepository
    profiles: TranslationProfileRepository
    providers: ProviderRepository
    connections: ProviderConnectionRepository
    credentials: ProviderCredentialRepository
    models: ProviderModelRepository
    capabilities: ModelCapabilityRepository
    glossaries: GlossaryRepository
    glossary_terms: GlossaryTermRepository
    memory: TranslationMemoryRepository
    wallets: CreditWalletRepository
    transactions: CreditTransactionRepository
    usage_events: UsageEventRepository
    languages: LanguageRepository
    language_variants: LanguageVariantRepository
    settings: SystemSettingRepository
    prompt_templates: PromptTemplateRepository
    prompt_versions: PromptVersionRepository
    users: UserRepository
    workers: WorkerRepository


def build_repositories(client: PocketBaseClient, *, token: str | None) -> Repositories:
    return Repositories(
        workspaces=WorkspaceRepository(client, token=token),
        workspace_members=WorkspaceMemberRepository(client, token=token),
        documents=DocumentRepository(client, token=token),
        document_sections=DocumentSectionRepository(client, token=token),
        jobs=TranslationJobRepository(client, token=token),
        segments=TranslationSegmentRepository(client, token=token),
        attempts=TranslationAttemptRepository(client, token=token),
        job_events=JobEventRepository(client, token=token),
        profiles=TranslationProfileRepository(client, token=token),
        providers=ProviderRepository(client, token=token),
        connections=ProviderConnectionRepository(client, token=token),
        credentials=ProviderCredentialRepository(client, token=token),
        models=ProviderModelRepository(client, token=token),
        capabilities=ModelCapabilityRepository(client, token=token),
        glossaries=GlossaryRepository(client, token=token),
        glossary_terms=GlossaryTermRepository(client, token=token),
        memory=TranslationMemoryRepository(client, token=token),
        wallets=CreditWalletRepository(client, token=token),
        transactions=CreditTransactionRepository(client, token=token),
        usage_events=UsageEventRepository(client, token=token),
        languages=LanguageRepository(client, token=token),
        language_variants=LanguageVariantRepository(client, token=token),
        settings=SystemSettingRepository(client, token=token),
        prompt_templates=PromptTemplateRepository(client, token=token),
        prompt_versions=PromptVersionRepository(client, token=token),
        users=UserRepository(client, token=token),
        workers=WorkerRepository(client, token=token),
    )
