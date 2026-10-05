"""S3-compatible object storage backend.

boto3 is synchronous; each call is dispatched to a worker thread via anyio so it
never blocks the event loop.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import anyio
import boto3
from botocore.exceptions import ClientError

from app.storage.base import StoredObject, validate_key


class S3Storage:
    """Stores objects in an S3-compatible bucket."""

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None = None,
        region: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
    ) -> None:
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    async def put(
        self,
        key: str,
        data: bytes | AsyncIterator[bytes],
        *,
        content_type: str | None = None,
    ) -> StoredObject:
        validate_key(key)
        if isinstance(data, bytes):
            payload = data
        else:
            # ponytail: buffers the object in memory; switch to multipart
            # streaming upload when large-document memory becomes a concern.
            buffer = bytearray()
            async for chunk in data:
                buffer.extend(chunk)
            payload = bytes(buffer)

        extra: dict[str, Any] = {}
        if content_type:
            extra["ContentType"] = content_type
        await anyio.to_thread.run_sync(
            lambda: self._client.put_object(Bucket=self._bucket, Key=key, Body=payload, **extra)
        )
        return StoredObject(key=key, size=len(payload), content_type=content_type)

    async def read(self, key: str) -> bytes:
        validate_key(key)

        def _get() -> bytes:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            body: bytes = response["Body"].read()
            return body

        return await anyio.to_thread.run_sync(_get)

    async def stream(self, key: str, *, chunk_size: int = 64 * 1024) -> AsyncIterator[bytes]:
        validate_key(key)
        response = await anyio.to_thread.run_sync(
            lambda: self._client.get_object(Bucket=self._bucket, Key=key)
        )
        body = response["Body"]
        try:
            while True:
                chunk = await anyio.to_thread.run_sync(body.read, chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            await anyio.to_thread.run_sync(body.close)

    async def exists(self, key: str) -> bool:
        validate_key(key)

        def _head() -> bool:
            try:
                self._client.head_object(Bucket=self._bucket, Key=key)
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey"):
                    return False
                raise
            return True

        return await anyio.to_thread.run_sync(_head)

    async def delete(self, key: str) -> None:
        validate_key(key)
        await anyio.to_thread.run_sync(
            lambda: self._client.delete_object(Bucket=self._bucket, Key=key)
        )

    async def generate_download_url(self, key: str, *, expires_seconds: int = 3600) -> str | None:
        validate_key(key)

        def _sign() -> str:
            url: str = self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires_seconds,
            )
            return url

        return await anyio.to_thread.run_sync(_sign)
