"""Shared test fixtures.

Tests are hermetic: no live PocketBase is required. Upstream HTTP is mocked and
the application context is constructed with test settings.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

# Ensure import-time Settings construction has the required secrets.
os.environ.setdefault("APP_SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENCRYPTION_KEY", "test-encryption-key")
os.environ.setdefault("WORKER_INTERNAL_TOKEN", "test-worker-token")
os.environ.setdefault("APP_ENV", "test")

from app.config import Settings
from app.repositories.pocketbase import PocketBaseClient
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.fakes import FakePocketBase


@pytest.fixture
def fake_pb() -> FakePocketBase:
    return FakePocketBase()


@pytest.fixture
async def pb(fake_pb: FakePocketBase) -> AsyncIterator[PocketBaseClient]:
    client = fake_pb.client()
    try:
        yield PocketBaseClient(str(client.base_url), client=client)
    finally:
        await client.aclose()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        app_secret_key="test-secret-key",
        encryption_key="test-encryption-key",
        worker_internal_token="test-worker-token",
        storage_local_root=tmp_path / "storage",
        log_level="WARNING",
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    from app.main import create_app

    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
