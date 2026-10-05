"""SSRF enforcement in the provider runtime."""

from __future__ import annotations

import pytest
from app.exceptions import ConfigurationError
from app.providers.credentials import ProviderCredentialService
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.providers.runtime import ProviderRuntime
from app.repositories.providers import (
    ProviderConnectionRepository,
    ProviderCredentialRepository,
    ProviderRepository,
)
from app.security.crypto import SecretCipher


def _runtime(pb) -> ProviderRuntime:
    return ProviderRuntime(
        connections=ProviderConnectionRepository(pb),
        providers=ProviderRepository(pb),
        credentials=ProviderCredentialService(
            ProviderCredentialRepository(pb), SecretCipher.from_secret("k")
        ),
    )


def _seed(fake_pb, *, base_url: str, config: dict[str, object] | None = None) -> str:
    provider = fake_pb.seed(
        "providers",
        {
            "name": "P",
            "slug": "p",
            "provider_type": "openai_compatible",
            "authentication_type": "api_key",
            "base_url": "https://1.1.1.1/v1",
            "enabled": True,
        },
    )
    connection = fake_pb.seed(
        "provider_connections",
        {
            "workspace": "w1",
            "provider": provider["id"],
            "name": "c",
            "auth_type": "api_key",
            "base_url": base_url,
            "config": config or {},
            "enabled": True,
        },
    )
    return connection["id"]


async def test_private_endpoint_rejected_by_default(pb, fake_pb) -> None:
    connection_id = _seed(fake_pb, base_url="http://10.0.0.5/v1")
    with pytest.raises(ConfigurationError):
        await _runtime(pb).build(
            connection_id=connection_id, provider_id=None, model_identifier="m"
        )


async def test_private_endpoint_allowed_when_configured(pb, fake_pb) -> None:
    connection_id = _seed(fake_pb, base_url="http://10.0.0.5/v1", config={"allow_private": True})
    provider = await _runtime(pb).build(
        connection_id=connection_id, provider_id=None, model_identifier="m"
    )
    assert isinstance(provider, OpenAICompatibleProvider)
    await provider.aclose()


async def test_public_endpoint_allowed(pb, fake_pb) -> None:
    connection_id = _seed(fake_pb, base_url="https://1.1.1.1/v1")
    provider = await _runtime(pb).build(
        connection_id=connection_id, provider_id=None, model_identifier="m"
    )
    assert isinstance(provider, OpenAICompatibleProvider)
    await provider.aclose()
