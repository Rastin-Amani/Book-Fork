"""Strongly typed application configuration.

This module contains **infrastructure and secret configuration only**. Anything
that describes business/translation behaviour (languages, providers, models,
prompts, per-book pricing, file/page limits, chunk sizes, ...) belongs
in PocketBase records and is loaded at runtime — never here and never hardcoded.

See ``docs/configuration.md`` for the full matrix of settings.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["development", "test", "production"]
StorageBackend = Literal["local", "s3"]
SameSite = Literal["lax", "strict", "none"]


class Settings(BaseSettings):
    """Runtime configuration sourced from environment variables / ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -- application ---------------------------------------------------------
    app_env: AppEnv = "development"
    app_name: str = "Book Fork"
    app_base_url: str = "http://localhost:8000"
    app_secret_key: SecretStr
    debug: bool = False

    # -- logging -------------------------------------------------------------
    log_level: str = "INFO"
    log_json: bool = False

    # -- PocketBase ----------------------------------------------------------
    pocketbase_url: str = "http://127.0.0.1:8090"
    pocketbase_service_credential: SecretStr | None = None
    pocketbase_users_collection: str = "users"

    # -- sessions / cookies --------------------------------------------------
    session_cookie_name: str = "book_fork_session"
    session_max_age_seconds: int = 60 * 60 * 24 * 14
    cookie_domain: str | None = None
    cookie_secure: bool | None = None  # derived from app_env when unset
    cookie_samesite: SameSite = "lax"

    # -- secrets management --------------------------------------------------
    encryption_key: SecretStr

    # -- worker --------------------------------------------------------------
    worker_internal_token: SecretStr

    # -- storage -------------------------------------------------------------
    storage_backend: StorageBackend = "local"
    storage_local_root: Path = Path("var/storage")
    s3_endpoint: str | None = None
    s3_bucket: str | None = None
    s3_access_key: SecretStr | None = None
    s3_secret_key: SecretStr | None = None
    s3_region: str | None = None

    # -- document processing (safety ceilings; NOT product limits) ----------
    document_temp_root: Path = Path("var/tmp")
    document_max_uncompressed_bytes: int = 500 * 1024 * 1024
    document_max_archive_entries: int = 5000
    document_max_compression_ratio: float = 200.0
    document_max_text_blocks: int = 200_000
    document_max_pdf_pages: int = 5000
    document_render_backend: str = "pymupdf"
    document_font_dir: Path | None = None
    # Formats produced for every completed job (comma-separated). An unavailable
    # format is skipped, not fatal.
    document_output_formats: str = "epub,pdf"
    document_book_page_size: str = "a5"
    ocr_provider: str = "none"

    # -- web / transport security -------------------------------------------
    # NOTE: this is a *transport* safety ceiling, not the product file-size
    # limit. The user-facing document size/page limit is business configuration
    # stored in PocketBase.
    max_request_bytes: int = 100 * 1024 * 1024
    trusted_hosts: list[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "testserver"]
    )
    cors_origins: list[str] = Field(default_factory=list)
    enable_docs: bool = True

    # -- rate limiting -------------------------------------------------------
    rate_limit_enabled: bool = True
    rate_limit_auth_per_minute: int = 30
    rate_limit_signup_per_minute: int = 10
    rate_limit_password_reset_per_minute: int = 10
    rate_limit_upload_per_minute: int = 20
    rate_limit_provider_test_per_minute: int = 20
    rate_limit_translation_per_minute: int = 30
    rate_limit_retry_per_minute: int = 30

    # -- browser security headers -------------------------------------------
    security_headers_enabled: bool = True
    # Override to tighten/replace the default HTMX+Alpine-compatible policy.
    content_security_policy: str | None = None

    # -- reverse proxy / deployment -----------------------------------------
    # Comma-separated list of proxies whose X-Forwarded-* headers are trusted.
    forwarded_allow_ips: str = "127.0.0.1"
    root_path: str = ""

    @model_validator(mode="after")
    def _derive_and_validate(self) -> Settings:
        if self.cookie_secure is None:
            object.__setattr__(self, "cookie_secure", self.app_env == "production")

        if self.app_env == "production" and not self.cookie_secure:
            raise ValueError("cookie_secure must be true in production")

        if self.storage_backend == "s3":
            missing = [
                name
                for name, value in {
                    "s3_bucket": self.s3_bucket,
                    "s3_access_key": self.s3_access_key,
                    "s3_secret_key": self.s3_secret_key,
                }.items()
                if value in (None, "")
            ]
            if missing:
                raise ValueError(f"storage_backend='s3' requires: {', '.join(missing)}")
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_test(self) -> bool:
        return self.app_env == "test"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()


def reset_settings_cache() -> None:
    """Clear the cached settings (used by tests when env changes)."""
    get_settings.cache_clear()
