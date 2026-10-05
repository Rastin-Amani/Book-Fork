"""Unit tests for the local storage backend and key safety."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from app.exceptions import ValidationError
from app.storage.local import LocalStorage


async def _stream(*chunks: bytes) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk


async def test_put_read_exists_delete(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    await storage.put("docs/a.bin", b"hello")
    assert await storage.exists("docs/a.bin")
    assert await storage.read("docs/a.bin") == b"hello"
    await storage.delete("docs/a.bin")
    assert not await storage.exists("docs/a.bin")


async def test_put_streams_and_reports_size(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    result = await storage.put("docs/big.bin", _stream(b"aa", b"bbb", b"c"))
    assert result.size == 6
    chunks = [c async for c in storage.stream("docs/big.bin", chunk_size=2)]
    assert b"".join(chunks) == b"aabbbc"


@pytest.mark.parametrize("key", ["../escape", "a/../../b", "/abs", "a//b", "a/./b", "..\\win"])
async def test_rejects_unsafe_keys(tmp_path: Path, key: str) -> None:
    storage = LocalStorage(tmp_path)
    with pytest.raises(ValidationError):
        await storage.put(key, b"x")
