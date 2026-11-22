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


def test_billing_is_off_and_needs_no_gumroad_config_by_default() -> None:
    settings = _base()
    assert settings.billing_enabled is False
    assert settings.payment_provider == "gumroad"
    assert settings.gumroad_access_token is None


def test_enabled_billing_requires_gumroad_and_service_credential() -> None:
    with pytest.raises(ValidationError, match="gumroad_access_token"):
        _base(billing_enabled=True)

    with pytest.raises(ValidationError, match="pocketbase_service_credential"):
        _base(
            billing_enabled=True,
            gumroad_access_token="token",
            gumroad_webhook_secret="s" * 32,
            gumroad_product_id="prod",
            gumroad_product_permalink="book",
        )

    settings = _base(
        billing_enabled=True,
        gumroad_access_token="token",
        gumroad_webhook_secret="s" * 32,
        gumroad_product_id="prod",
        gumroad_product_permalink="book",
        pocketbase_service_credential="svc",
    )
    assert settings.billing_enabled is True


def test_enabled_billing_rejects_another_provider() -> None:
    with pytest.raises(ValidationError, match="gumroad"):
        _base(
            billing_enabled=True,
            payment_provider="stripe",
            gumroad_access_token="token",
            gumroad_webhook_secret="s" * 32,
            gumroad_product_id="prod",
            gumroad_product_permalink="book",
            pocketbase_service_credential="svc",
        )


def test_webhook_secret_must_be_long_and_permalink_a_slug() -> None:
    base = {
        "billing_enabled": True,
        "gumroad_access_token": "token",
        "gumroad_product_id": "prod",
        "pocketbase_service_credential": "svc",
    }
    with pytest.raises(ValidationError, match="at least 32"):
        _base(**base, gumroad_webhook_secret="short", gumroad_product_permalink="book")
    with pytest.raises(ValidationError, match="invalid characters"):
        _base(**base, gumroad_webhook_secret="s" * 32, gumroad_product_permalink="a/b")
