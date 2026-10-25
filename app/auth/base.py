"""Authentication abstraction.

The rest of the application depends on this interface, never on PocketBase
auth details directly. This keeps the identity provider replaceable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

# Sign-in providers offered by the UI, in display order.
OAUTH_PROVIDERS: dict[str, str] = {"google": "Google", "github": "GitHub"}


@dataclass(frozen=True, slots=True)
class AuthUser:
    """Provider-agnostic authenticated user."""

    id: str
    email: str | None
    name: str | None
    verified: bool


@dataclass(frozen=True, slots=True)
class AuthSession:
    """An issued session: an opaque bearer token plus the resolved user."""

    token: str
    user: AuthUser


@dataclass(frozen=True, slots=True)
class OAuthProvider:
    """One enabled provider as offered by the identity service."""

    name: str
    auth_url: str
    state: str
    verifier: str


@runtime_checkable
class AuthProvider(Protocol):
    """Identity operations required by the application."""

    async def oauth_providers(self) -> list[OAuthProvider]:
        """Enabled Google/GitHub providers, in UI order."""
        ...

    async def login_with_oauth2(
        self, *, provider: str, code: str, code_verifier: str, redirect_url: str
    ) -> AuthSession:
        """Exchange an OAuth2 authorization code for a session."""
        ...

    async def refresh(self, *, token: str) -> AuthSession:
        """Validate a token and return the current user (token may rotate)."""
        ...

    async def logout(self, *, token: str) -> None:
        """Invalidate a session token where the provider supports it."""
        ...
