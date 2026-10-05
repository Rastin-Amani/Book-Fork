"""Run the configurable data-retention sweep.

Usage::

    uv run python scripts/retention.py

Requires ``POCKETBASE_SERVICE_CREDENTIAL``. Deletes only what the
``retention.*`` system settings permit; absent settings mean "keep".
"""

from __future__ import annotations

import anyio
from app.config import get_settings
from app.logging import configure_logging, get_logger
from app.repositories.documents import DocumentRepository
from app.repositories.pocketbase import PocketBaseClient
from app.repositories.settings import SystemSettingRepository
from app.repositories.translation import (
    JobEventRepository,
    TranslationAttemptRepository,
    TranslationJobRepository,
    TranslationSegmentRepository,
)
from app.services.retention import RetentionService
from app.settings.service import SettingsService
from app.storage.factory import build_storage

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
        raise SystemExit("POCKETBASE_SERVICE_CREDENTIAL is required to run retention.")

    client = PocketBaseClient(settings.pocketbase_url)
    storage = build_storage(settings)
    try:
        token = await _service_token(
            client, settings.pocketbase_service_credential.get_secret_value()
        )
        service = RetentionService(
            documents=DocumentRepository(client, token=token),
            jobs=TranslationJobRepository(client, token=token),
            segments=TranslationSegmentRepository(client, token=token),
            attempts=TranslationAttemptRepository(client, token=token),
            events=JobEventRepository(client, token=token),
            storage=storage,
            settings=SettingsService(SystemSettingRepository(client, token=token), token=token),
            temp_root=settings.document_temp_root,
            token=token,
        )
        report = await service.run()
        logger.info("retention_complete", **report.as_dict())
    finally:
        await client.aclose()


def main() -> None:
    anyio.run(run)


if __name__ == "__main__":
    main()
