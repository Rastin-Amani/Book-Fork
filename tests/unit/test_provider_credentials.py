"""Provider credentials: encrypted at rest, never logged."""

from __future__ import annotations

from app.providers.credentials import ProviderCredentialService, key_hint
from app.repositories.providers import ProviderCredentialRepository
from app.security.crypto import SecretCipher


def test_key_hint_is_not_reversible() -> None:
    assert key_hint("sk-abcdef1234") == "…1234"
    assert key_hint("x") == "…"


async def test_store_encrypts_and_resolve_decrypts(pb, fake_pb) -> None:
    fake_pb.seed(
        "provider_connections",
        {"workspace": "w1", "provider": "p1", "name": "mine", "auth_type": "api_key"},
    )
    service = ProviderCredentialService(
        ProviderCredentialRepository(pb), SecretCipher.from_secret("master-key")
    )
    record = await service.store("conn1", "sk-super-secret")
    assert "sk-super-secret" not in record.encrypted_credential
    assert record.key_hint == "…cret"
    assert await service.resolve("conn1") == "sk-super-secret"


async def test_resolve_missing_returns_none(pb) -> None:
    service = ProviderCredentialService(
        ProviderCredentialRepository(pb), SecretCipher.from_secret("k")
    )
    assert await service.resolve("nope") is None
