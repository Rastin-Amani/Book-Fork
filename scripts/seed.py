"""Apply Book Fork data seeds to the configured PocketBase.

Usage::

    uv run python scripts/seed.py

Requires ``POCKETBASE_SERVICE_CREDENTIAL``, either a superuser token or
``identity:password`` (exchanged for a short-lived token).
"""

from __future__ import annotations

import anyio
from app.config import get_settings
from app.logging import configure_logging, get_logger
from app.repositories.languages import LanguageRepository, LanguageVariantRepository
from app.repositories.pocketbase import PocketBaseClient
from app.repositories.prompts import PromptTemplateRepository, PromptVersionRepository
from app.repositories.providers import ProviderRepository
from app.repositories.settings import SystemSettingRepository
from app.repositories.translation import TranslationProfileRepository
from app.services.seed import SeedService

logger = get_logger(__name__)


async def _service_token(client: PocketBaseClient, credential: str) -> str:
    if ":" in credential:
        identity, password = credential.split(":", 1)
        return await client.authenticate_superuser(identity=identity, password=password)
    return credential


async def run() -> None:
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.log_json)

    if settings.pocketbase_service_credential is None:
        logger.error("missing_service_credential")
        raise SystemExit("POCKETBASE_SERVICE_CREDENTIAL is required to seed.")

    client = PocketBaseClient(settings.pocketbase_url)
    try:
        token = await _service_token(
            client, settings.pocketbase_service_credential.get_secret_value()
        )
        service = SeedService(
            languages=LanguageRepository(client, token=token),
            variants=LanguageVariantRepository(client, token=token),
            settings=SystemSettingRepository(client, token=token),
            providers=ProviderRepository(client, token=token),
            profiles=TranslationProfileRepository(client, token=token),
            templates=PromptTemplateRepository(client, token=token),
            versions=PromptVersionRepository(client, token=token),
            token=token,
        )
        report = await service.run()
        logger.info("seed_complete", summary=report.summary())
    finally:
        await client.aclose()


def main() -> None:
    anyio.run(run)


if __name__ == "__main__":
    main()
