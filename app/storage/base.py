"""Storage abstraction.

Document processing must not know whether bytes live on the local filesystem or
in S3-compatible object storage. Everything goes through this interface.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.exceptions import ValidationError


@dataclass(frozen=True, slots=True)
class StoredObject:
    """Metadata for a stored object."""

    key: str
    size: int
    content_type: str | None = None


def validate_key(key: str) -> str:
    """Reject keys that could escape the storage root or be ambiguous."""
    if not key or key.startswith("/") or "\\" in key:
        raise ValidationError("Invalid storage key.")
    parts = key.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValidationError("Invalid storage key.")
    return key


@runtime_checkable
class Storage(Protocol):
    """Backend-agnostic byte storage."""

    async def put(
        self,
        key: str,
        data: bytes | AsyncIterator[bytes],
        *,
        content_type: str | None = None,
    ) -> StoredObject:
        """Store ``data`` under ``key`` and return its metadata."""
        ...

    async def read(self, key: str) -> bytes:
        """Return the full object contents."""
        ...

    def stream(self, key: str, *, chunk_size: int = 64 * 1024) -> AsyncIterator[bytes]:
        """Yield the object contents in chunks (async generator)."""
        ...

    async def exists(self, key: str) -> bool:
        """Return whether an object exists."""
        ...

    async def delete(self, key: str) -> None:
        """Delete an object; missing objects are ignored."""
        ...

    async def generate_download_url(self, key: str, *, expires_seconds: int = 3600) -> str | None:
        """Return a time-limited download URL, or None when the app streams it."""
        ...
