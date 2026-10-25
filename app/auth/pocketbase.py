"""PocketBase-backed authentication provider.

Maps PocketBase auth responses onto the provider-agnostic types in
:mod:`app.auth.base`. This is the only auth module that talks to PocketBase.
"""

from __future__ import annotations

from typing import Any

from app.auth.base import OAUTH_PROVIDERS, AuthSession, AuthUser, OAuthProvider
from app.repositories.pocketbase import PocketBaseClient
from app.schemas.pocketbase import PocketBaseRecord


def _to_user(record: PocketBaseRecord) -> AuthUser:
    return AuthUser(
        id=record.id,
        email=record.email,
        name=record.name,
        verified=bool(record.verified),
    )


class PocketBaseAuthProvider:
    """Authentication against a PocketBase ``users``-style collection."""

    def __init__(self, client: PocketBaseClient, *, users_collection: str = "users") -> None:
        self._client = client
        self._collection = users_collection

    async def oauth_providers(self) -> list[OAuthProvider]:
        methods: dict[str, Any] = await self._client.auth_methods(self._collection)
        oauth2 = methods.get("oauth2") or {}
        if not oauth2.get("enabled"):
            return []

        found: dict[str, OAuthProvider] = {}
        for item in oauth2.get("providers") or []:
            name = str(item.get("name") or "")
            auth_url = str(item.get("authUrl") or item.get("authURL") or "")
            state = str(item.get("state") or "")
            verifier = str(item.get("codeVerifier") or "")
            if name in OAUTH_PROVIDERS and auth_url and state and verifier:
                found[name] = OAuthProvider(
                    name=name, auth_url=auth_url, state=state, verifier=verifier
                )
        return [found[name] for name in OAUTH_PROVIDERS if name in found]

    async def login_with_oauth2(
        self, *, provider: str, code: str, code_verifier: str, redirect_url: str
    ) -> AuthSession:
        result = await self._client.auth_with_oauth2(
            self._collection,
            provider=provider,
            code=code,
            code_verifier=code_verifier,
            redirect_url=redirect_url,
        )
        return AuthSession(token=result.token, user=_to_user(result.record))

    async def refresh(self, *, token: str) -> AuthSession:
        result = await self._client.auth_refresh(self._collection, token=token)
        return AuthSession(token=result.token, user=_to_user(result.record))

    async def logout(self, *, token: str) -> None:
        # PocketBase stateless tokens cannot be revoked server-side without an
        # auth store; clearing the client cookie is the effective logout.
        return None
