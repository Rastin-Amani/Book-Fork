"""Storage backends: download URL behaviour for the local backend."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.exceptions import ValidationError
from app.storage.local import LocalStorage


async def test_local_backend_streams_itself(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    await storage.put("docs/a.bin", b"data")
    assert await storage.generate_download_url("docs/a.bin") is None


async def test_download_url_validates_key(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)
    with pytest.raises(ValidationError):
        await storage.generate_download_url("../escape")
