"""Storage backend factory."""

from __future__ import annotations

from app.config import Settings
from app.storage.base import Storage
from app.storage.local import LocalStorage
from app.storage.s3 import S3Storage


def build_storage(settings: Settings) -> Storage:
    """Construct the configured storage backend."""
    if settings.storage_backend == "s3":
        return S3Storage(
            bucket=settings.s3_bucket or "",
            endpoint_url=settings.s3_endpoint,
            region=settings.s3_region,
            access_key=(
                settings.s3_access_key.get_secret_value() if settings.s3_access_key else None
            ),
            secret_key=(
                settings.s3_secret_key.get_secret_value() if settings.s3_secret_key else None
            ),
        )
    return LocalStorage(settings.storage_local_root)
