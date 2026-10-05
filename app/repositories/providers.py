"""Provider, connection, model, and capability repositories."""

from __future__ import annotations

from app.repositories.base import PocketBaseRepository, escape_filter_value, filter_eq
from app.schemas.providers import (
    ModelCapability,
    Provider,
    ProviderConnection,
    ProviderCredential,
    ProviderModel,
)


class ProviderRepository(PocketBaseRepository[Provider]):
    collection = "providers"
    model = Provider

    async def get_by_slug(self, slug: str, *, token: str | None = None) -> Provider | None:
        return await self.first(filter=filter_eq("slug", slug), token=token)

    async def list_enabled(self, *, token: str | None = None) -> list[Provider]:
        return await self.list(filter="enabled = true", token=token)


class ProviderConnectionRepository(PocketBaseRepository[ProviderConnection]):
    collection = "provider_connections"
    model = ProviderConnection

    async def list_for_workspace(
        self, workspace_id: str, *, token: str | None = None
    ) -> list[ProviderConnection]:
        return await self.list(filter=filter_eq("workspace", workspace_id), token=token)


class ProviderCredentialRepository(PocketBaseRepository[ProviderCredential]):
    """Server-only; requires the service credential token."""

    collection = "provider_credentials"
    model = ProviderCredential

    async def get_by_connection(
        self, connection_id: str, *, token: str | None = None
    ) -> ProviderCredential | None:
        return await self.first(filter=filter_eq("connection", connection_id), token=token)


class ProviderModelRepository(PocketBaseRepository[ProviderModel]):
    collection = "provider_models"
    model = ProviderModel

    async def list_for_provider(
        self, provider_id: str, *, token: str | None = None
    ) -> list[ProviderModel]:
        return await self.list(filter=filter_eq("provider", provider_id), token=token)

    async def get_by_identifier(
        self, provider_id: str, identifier: str, *, token: str | None = None
    ) -> ProviderModel | None:
        clause = (
            f'provider = "{escape_filter_value(provider_id)}"'
            f' && model_identifier = "{escape_filter_value(identifier)}"'
        )
        return await self.first(filter=clause, token=token)


class ModelCapabilityRepository(PocketBaseRepository[ModelCapability]):
    collection = "model_capabilities"
    model = ModelCapability

    async def list_for_pair(
        self, source_language: str, target_language: str, *, token: str | None = None
    ) -> list[ModelCapability]:
        clause = (
            filter_eq("source_language", source_language)
            + " && "
            + filter_eq("target_language", target_language)
        )
        return await self.list(filter=clause, token=token)
