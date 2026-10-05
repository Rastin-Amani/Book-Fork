"""Resolve a trusted service credential for server-side worker operations."""

from __future__ import annotations

from app.repositories.pocketbase import PocketBaseClient


async def resolve_service_token(client: PocketBaseClient, credential: str | None) -> str | None:
    """Return a service token from a token string or ``identity:password``."""
    if not credential:
        return None
    if ":" in credential:
        identity, password = credential.split(":", 1)
        return await client.authenticate_superuser(identity=identity, password=password)
    return credential
