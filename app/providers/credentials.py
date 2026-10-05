"""Provider credential storage.

API keys are stored encrypted at rest. The plaintext key exists only for the
brief lifetime of building a provider client, is never logged, and is never
returned to a frontend.
"""

from __future__ import annotations

from app.repositories.providers import ProviderCredentialRepository
from app.schemas.providers import ProviderCredential
from app.security.crypto import SecretCipher


def key_hint(api_key: str) -> str:
    """A non-reversible hint (last 4 chars) safe to display/log."""
    return f"…{api_key[-4:]}" if len(api_key) >= 4 else "…"


class ProviderCredentialService:
    """Encrypts and resolves provider API keys."""

    def __init__(
        self,
        repository: ProviderCredentialRepository,
        cipher: SecretCipher,
        *,
        token: str | None = None,
    ) -> None:
        self._repository = repository
        self._cipher = cipher
        self._token = token

    async def store(self, connection_id: str, api_key: str) -> ProviderCredential:
        encrypted = self._cipher.encrypt(api_key)
        existing = await self._repository.get_by_connection(connection_id, token=self._token)
        if existing is not None:
            return await self._repository.update(
                existing.id,
                {"encrypted_credential": encrypted, "key_hint": key_hint(api_key)},
                token=self._token,
            )
        return await self._repository.create(
            {
                "connection": connection_id,
                "encrypted_credential": encrypted,
                "key_hint": key_hint(api_key),
            },
            token=self._token,
        )

    async def resolve(self, connection_id: str) -> str | None:
        """Decrypt the key for a connection. Callers must not log or persist it."""
        credential = await self._repository.get_by_connection(connection_id, token=self._token)
        if credential is None:
            return None
        return self._cipher.decrypt(credential.encrypted_credential)
