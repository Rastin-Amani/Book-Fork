"""Authentication abstraction.

The rest of the application depends on this interface, never on PocketBase
auth details directly. This keeps the identity provider replaceable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


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


@runtime_checkable
class AuthProvider(Protocol):
    """Identity operations required by the application."""

    async def login(self, *, identity: str, password: str) -> AuthSession:
        """Authenticate with credentials and return a session."""
        ...

    async def signup(self, *, email: str, password: str, name: str | None = None) -> AuthSession:
        """Create a new user and return an authenticated session."""
        ...

    async def refresh(self, *, token: str) -> AuthSession:
        """Validate a token and return the current user (token may rotate)."""
        ...

    async def logout(self, *, token: str) -> None:
        """Invalidate a session token where the provider supports it."""
        ...

    async def request_password_reset(self, *, email: str) -> None:
        """Begin the password reset flow."""
        ...

    async def confirm_password_reset(
        self, *, token: str, password: str, password_confirm: str
    ) -> None:
        """Complete the password reset flow."""
        ...

    async def request_verification(self, *, email: str) -> None:
        """Begin the email verification flow."""
        ...

    async def confirm_verification(self, *, token: str) -> None:
        """Complete the email verification flow."""
        ...
