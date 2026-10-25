"""Authentication response schemas."""

from __future__ import annotations

from pydantic import BaseModel


class UserOut(BaseModel):
    """Public representation of the authenticated user."""

    id: str
    email: str | None
    name: str | None
    verified: bool
