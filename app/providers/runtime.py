"""Runtime provider resolution for the worker.

Combines a connection, its provider protocol, the model identifier and the
decrypted (short-lived) credential into a ready adapter. No vendor is hardcoded;
the protocol comes from the provider record.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.exceptions import ConfigurationError
from app.providers.base import TranslationProvider
from app.providers.credentials import ProviderCredentialService
from app.providers.factory import build_provider
from app.repositories.providers import (
    ProviderConnectionRepository,
    ProviderRepository,
)
from app.schemas.providers import ProviderConnection
from app.security.urls import is_safe_outbound_url


class ProviderRuntime:
    def __init__(
        self,
        *,
        connections: ProviderConnectionRepository,
        providers: ProviderRepository,
        credentials: ProviderCredentialService,
        token: str | None = None,
    ) -> None:
        self._connections = connections
        self._providers = providers
        self._credentials = credentials
        self._token = token

    async def connection(self, connection_id: str) -> ProviderConnection:
        return await self._connections.get(connection_id, token=self._token)

    async def build(
        self,
        *,
        connection_id: str,
        provider_id: str | None,
        model_identifier: str | None,
        options: Mapping[str, Any] | None = None,
    ) -> TranslationProvider:
        connection = await self._connections.get(connection_id, token=self._token)
        provider = await self._providers.get(
            connection.provider or provider_id or "", token=self._token
        )
        merged: dict[str, Any] = dict(provider.capabilities or {})
        merged.update(connection.config or {})
        merged.update(options or {})
        base_url = connection.base_url or provider.base_url or None
        if base_url and not is_safe_outbound_url(
            base_url, allow_private=bool(merged.get("allow_private", False))
        ):
            raise ConfigurationError("The provider endpoint URL is not allowed.")
        # Fall back to the connection's configured default model when the
        # policy selected none, so the request never sends a null model.
        resolved_model = model_identifier or merged.get("default_model")
        if not resolved_model:
            raise ConfigurationError(
                f"Provider connection {connection.name!r} has no model configured."
            )
        # The plaintext key exists only for the duration of building the client.
        api_key = await self._credentials.resolve(connection_id)
        return build_provider(
            provider_type=provider.provider_type.value,
            model_identifier=str(resolved_model),
            base_url=base_url,
            api_key=api_key,
            options=merged,
        )

    @staticmethod
    async def close(provider: TranslationProvider) -> None:
        closer = getattr(provider, "aclose", None)
        if closer is not None:
            await closer()
