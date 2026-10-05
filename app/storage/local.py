"""Local filesystem storage backend (development and simple deployments)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from anyio import Path as AsyncPath

from app.storage.base import StoredObject, validate_key


class LocalStorage:
    """Stores objects as files beneath a root directory."""

    def __init__(self, root: str | Path) -> None:
        self._root = AsyncPath(root)

    def _resolve(self, key: str) -> AsyncPath:
        validate_key(key)
        root = self._root
        candidate = root / key
        # Defense in depth: keys are validated, but confirm containment anyway.
        try:
            candidate.relative_to(root)
        except ValueError as exc:  # pragma: no cover - validate_key already blocks this
            raise ValueError("storage key escapes root") from exc
        return candidate

    async def put(
        self,
        key: str,
        data: bytes | AsyncIterator[bytes],
        *,
        content_type: str | None = None,
    ) -> StoredObject:
        path = self._resolve(key)
        await path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            await path.write_bytes(data)
            size = len(data)
        else:
            size = 0
            async with await path.open("wb") as handle:
                async for chunk in data:
                    size += len(chunk)
                    await handle.write(chunk)
        return StoredObject(key=key, size=size, content_type=content_type)

    async def read(self, key: str) -> bytes:
        return await self._resolve(key).read_bytes()

    async def stream(self, key: str, *, chunk_size: int = 64 * 1024) -> AsyncIterator[bytes]:
        path = self._resolve(key)
        async with await path.open("rb") as handle:
            while chunk := await handle.read(chunk_size):
                yield chunk

    async def exists(self, key: str) -> bool:
        return await self._resolve(key).exists()

    async def delete(self, key: str) -> None:
        await self._resolve(key).unlink(missing_ok=True)

    async def generate_download_url(self, key: str, *, expires_seconds: int = 3600) -> str | None:
        # Local files are streamed by the application, not exposed directly.
        validate_key(key)
        return None
