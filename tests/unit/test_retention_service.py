"""Configurable data retention sweep."""

from __future__ import annotations

import os
import time
from pathlib import Path

from app.repositories.documents import DocumentRepository
from app.repositories.settings import SystemSettingRepository
from app.repositories.translation import (
    JobEventRepository,
    TranslationAttemptRepository,
    TranslationJobRepository,
    TranslationSegmentRepository,
)
from app.services.retention import RetentionService
from app.settings.service import SettingsService
from app.storage.local import LocalStorage


def _service(pb, storage: LocalStorage, *, temp_root: Path | None = None) -> RetentionService:
    return RetentionService(
        documents=DocumentRepository(pb),
        jobs=TranslationJobRepository(pb),
        segments=TranslationSegmentRepository(pb),
        attempts=TranslationAttemptRepository(pb),
        events=JobEventRepository(pb),
        storage=storage,
        settings=SettingsService(SystemSettingRepository(pb)),
        temp_root=temp_root,
    )


def _setting(fake_pb, key: str, value: object, type_: str) -> None:
    fake_pb.seed("system_settings", {"key": key, "value": value, "type": type_})


async def test_no_setting_keeps_documents(pb, fake_pb, tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path / "store")
    await storage.put("documents/d1/source.epub", b"data")
    fake_pb.seed(
        "documents",
        {
            "id": "d1",
            "workspace": "w1",
            "original_filename": "book.epub",
            "created_by": "u1",
            "storage_key": "documents/d1/source.epub",
            "status": "ready",
            "created": "2020-01-01 00:00:00Z",
        },
    )
    report = await _service(pb, storage).run()
    assert report.documents_deleted == 0
    assert await storage.exists("documents/d1/source.epub")


async def test_old_documents_are_swept_with_storage(pb, fake_pb, tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path / "store")
    await storage.put("documents/d1/source.epub", b"data")
    await storage.put("documents/d1/canonical/v1.json", b"{}")
    _setting(fake_pb, "retention.source_documents_days", 1, "int")
    fake_pb.seed(
        "documents",
        {
            "id": "d1",
            "workspace": "w1",
            "original_filename": "book.epub",
            "created_by": "u1",
            "storage_key": "documents/d1/source.epub",
            "status": "ready",
            "created": "2020-01-01 00:00:00Z",
        },
    )
    report = await _service(pb, storage).run()
    assert report.documents_deleted == 1
    assert not await storage.exists("documents/d1/source.epub")
    assert "d1" not in fake_pb.collections.get("documents", {})


async def test_active_job_protects_document(pb, fake_pb, tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path / "store")
    _setting(fake_pb, "retention.source_documents_days", 1, "int")
    fake_pb.seed(
        "documents",
        {
            "id": "d1",
            "workspace": "w1",
            "original_filename": "book.epub",
            "created_by": "u1",
            "storage_key": "documents/d1/source.epub",
            "status": "ready",
            "created": "2020-01-01 00:00:00Z",
        },
    )
    fake_pb.seed("translation_jobs", {"document": "d1", "status": "translating"})
    report = await _service(pb, storage).run()
    assert report.documents_deleted == 0


async def test_temp_files_swept(pb, fake_pb, tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path / "store")
    temp_root = tmp_path / "tmp"
    temp_root.mkdir()
    stale = temp_root / "old.bin"
    stale.write_bytes(b"x")
    old = time.time() - 48 * 3600
    os.utime(stale, (old, old))
    _setting(fake_pb, "retention.temp_files_hours", 1, "int")
    report = await _service(pb, storage, temp_root=temp_root).run()
    assert report.temp_files_deleted == 1
    assert not stale.exists()
