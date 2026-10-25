"""Durable translation worker entrypoint.

Run with::

    uv run python -m worker.main                 # continuous
    uv run python -m worker.main --once          # process at most one job
    uv run python -m worker.main --job-id <id>   # run a specific job
    uv run python -m worker.main --concurrency 4 # override max concurrent jobs

The worker is a separate process from the API and never uses BackgroundTasks.
It requires ``POCKETBASE_SERVICE_CREDENTIAL`` (a superuser token or
``identity:password``) to act on jobs across workspaces.
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import uuid
from dataclasses import replace

from app.config import get_settings
from app.context import build_context, close_context
from app.documents.adapters.base import DocumentType
from app.documents.service import DocumentEngine
from app.jobs.config import load_worker_settings
from app.jobs.retry import RetryService
from app.jobs.store import PocketBaseJobStore
from app.logging import configure_logging, get_logger
from app.providers.base import TranslationProvider
from app.providers.credentials import ProviderCredentialService
from app.providers.runtime import ProviderRuntime
from app.repositories.documents import DocumentRepository
from app.repositories.knowledge import GlossaryTermRepository, TranslationMemoryRepository
from app.repositories.languages import LanguageRepository
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
from app.repositories.workers import WorkerRepository
from app.schemas.translation import TranslationJob
from app.security.crypto import SecretCipher
from app.services.service_auth import resolve_service_token
from app.settings.service import SettingsService
from app.translation.engine import TranslationEngine
from app.translation.glossary import GlossaryRetriever
from app.translation.memory import TranslationMemory, TranslationMemoryStore
from app.translation.plan import TranslationPlan
from app.translation.policy import TranslationPolicyService
from app.translation.policy_engine import TranslationPolicyEngine
from app.version import __version__

from worker.heartbeat import WorkerRegistry
from worker.job_executor import JobExecutor
from worker.runner import Worker

logger = get_logger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Book Fork translation worker")
    parser.add_argument("--once", action="store_true", help="Process at most one job then exit.")
    parser.add_argument("--job-id", default=None, help="Run a specific job id.")
    parser.add_argument(
        "--concurrency", type=int, default=None, help="Override max concurrent jobs."
    )
    return parser.parse_args(argv)


def _output_formats(raw: str) -> tuple[DocumentType, ...]:
    formats: list[DocumentType] = []
    for part in raw.split(","):
        value = part.strip().lower()
        if not value:
            continue
        try:
            formats.append(DocumentType(value))
        except ValueError:
            continue
    return tuple(formats) or (DocumentType.EPUB, DocumentType.PDF)


async def run(args: argparse.Namespace) -> None:
    app_settings = get_settings()
    configure_logging(level=app_settings.log_level, json_logs=app_settings.log_json)

    credential = (
        app_settings.pocketbase_service_credential.get_secret_value()
        if app_settings.pocketbase_service_credential
        else None
    )
    if not credential:
        raise SystemExit("POCKETBASE_SERVICE_CREDENTIAL is required to run the worker.")

    context = await build_context(app_settings)
    try:
        token = await resolve_service_token(context.pocketbase, credential)
        client = context.pocketbase
        jobs = TranslationJobRepository(client, token=token)
        segments = TranslationSegmentRepository(client, token=token)
        attempts = TranslationAttemptRepository(client, token=token)
        events = JobEventRepository(client, token=token)
        store = PocketBaseJobStore(
            jobs=jobs, segments=segments, attempts=attempts, events=events, token=token
        )
        settings_service = SettingsService(
            SystemSettingRepository(client, token=token), token=token
        )
        worker_settings = await load_worker_settings(settings_service)
        if args.concurrency is not None:
            worker_settings = replace(worker_settings, max_concurrent_jobs=max(1, args.concurrency))

        documents = DocumentEngine(temp_root=app_settings.document_temp_root)
        translation_engine = TranslationEngine()
        languages = LanguageRepository(client, token=token)
        from app.language.registry import PocketBaseLanguageRegistry

        policy = TranslationPolicyEngine(
            policy_service=TranslationPolicyService(
                profiles=TranslationProfileRepository(client, token=token),
                connections=ProviderConnectionRepository(client, token=token),
                models=ProviderModelRepository(client, token=token),
                capabilities=ModelCapabilityRepository(client, token=token),
                templates=PromptTemplateRepository(client, token=token),
                versions=PromptVersionRepository(client, token=token),
                settings=settings_service,
                token=token,
            ),
            languages=PocketBaseLanguageRegistry(languages, token=token),
            models=ProviderModelRepository(client, token=token),
            prompt_versions=PromptVersionRepository(client, token=token),
            settings=settings_service,
        )
        runtime = ProviderRuntime(
            connections=ProviderConnectionRepository(client, token=token),
            providers=ProviderRepository(client, token=token),
            credentials=ProviderCredentialService(
                ProviderCredentialRepository(client, token=token),
                SecretCipher.from_secret(app_settings.encryption_key.get_secret_value()),
                token=token,
            ),
            token=token,
        )

        async def provider_factory(
            job: TranslationJob, plan: TranslationPlan
        ) -> TranslationProvider:
            return await runtime.build(
                connection_id=plan.provider_connection_id or "",
                provider_id=plan.provider_id,
                model_identifier=plan.model_identifier,
            )

        def memory_factory(job: TranslationJob) -> TranslationMemoryStore | None:
            return TranslationMemory(
                TranslationMemoryRepository(client, token=token),
                workspace_id=job.workspace,
                token=token,
            )

        def glossary_factory(job: TranslationJob) -> GlossaryRetriever | None:
            ids = list((job.snapshot or {}).get("profile_snapshot", {}).get("glossary_ids") or [])
            if not ids:
                return None
            return GlossaryRetriever(GlossaryTermRepository(client, token=token), ids, token=token)

        executor = JobExecutor(
            store=store,
            documents=documents,
            policy=policy,
            engine=translation_engine,
            storage=context.storage,
            document_repository=DocumentRepository(client, token=token),
            provider_factory=provider_factory,
            settings=worker_settings,
            retry=RetryService(),
            memory_factory=memory_factory,
            glossary_factory=glossary_factory,
            temp_root=app_settings.document_temp_root,
            output_formats=_output_formats(app_settings.document_output_formats),
            page_size=app_settings.document_book_page_size,
            font_dir=(
                str(app_settings.document_font_dir) if app_settings.document_font_dir else None
            ),
            render_backend=app_settings.document_render_backend,
        )
        worker_id = f"worker-{uuid.uuid4().hex[:8]}"
        worker = Worker(
            store=store,
            executor=executor,
            settings=worker_settings,
            worker_id=worker_id,
            registry=WorkerRegistry(
                WorkerRepository(client, token=token),
                worker_id=worker_id,
                version=__version__,
                token=token,
            ),
        )

        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        await worker.run(once=args.once, job_id=args.job_id, stop=stop)
    finally:
        await close_context(context)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
