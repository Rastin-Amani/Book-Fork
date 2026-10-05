"""PocketBase-backed authentication provider.

Maps PocketBase auth responses onto the provider-agnostic types in
:mod:`app.auth.base`. This is the only auth module that talks to PocketBase.
"""

from __future__ import annotations

from app.auth.base import AuthSession, AuthUser
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

    async def login(self, *, identity: str, password: str) -> AuthSession:
        result = await self._client.auth_with_password(
            self._collection, identity=identity, password=password
        )
        return AuthSession(token=result.token, user=_to_user(result.record))

    async def signup(self, *, email: str, password: str, name: str | None = None) -> AuthSession:
        data: dict[str, object] = {
            "email": email,
            "password": password,
            "passwordConfirm": password,
        }
        if name:
            data["name"] = name
        await self._client.create_record(self._collection, data)
        # PocketBase record creation does not return an auth token; log in.
        return await self.login(identity=email, password=password)

    async def refresh(self, *, token: str) -> AuthSession:
        result = await self._client.auth_refresh(self._collection, token=token)
        return AuthSession(token=result.token, user=_to_user(result.record))

    async def logout(self, *, token: str) -> None:
        # PocketBase stateless tokens cannot be revoked server-side without an
        # auth store; clearing the client cookie is the effective logout.
        return None

    async def request_password_reset(self, *, email: str) -> None:
        await self._client.request_password_reset(self._collection, email=email)

    async def confirm_password_reset(
        self, *, token: str, password: str, password_confirm: str
    ) -> None:
        await self._client.confirm_password_reset(
            self._collection, token=token, password=password, password_confirm=password_confirm
        )

    async def request_verification(self, *, email: str) -> None:
        await self._client.request_verification(self._collection, email=email)

    async def confirm_verification(self, *, token: str) -> None:
        await self._client.confirm_verification(self._collection, token=token)
