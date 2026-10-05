"""Unit tests for configuration validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from app.config import Settings
from pydantic import ValidationError


def _base(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "app_secret_key": "s",
        "encryption_key": "e",
        "worker_internal_token": "w",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_cookie_secure_derived_from_env() -> None:
    assert _base(app_env="development").cookie_secure is False
    assert _base(app_env="production").cookie_secure is True


def test_production_requires_secure_cookie() -> None:
    with pytest.raises(ValidationError):
        _base(app_env="production", cookie_secure=False)


def test_s3_backend_requires_credentials() -> None:
    with pytest.raises(ValidationError):
        _base(storage_backend="s3")


def test_local_storage_is_default(tmp_path: Path) -> None:
    settings = _base(storage_local_root=tmp_path)
    assert settings.storage_backend == "local"
    assert settings.is_production is False
