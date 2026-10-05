"""Settings-driven usage limits (abuse prevention)."""

from __future__ import annotations

import pytest
from app.exceptions import UsageLimitError
from app.repositories.documents import DocumentRepository
from app.repositories.settings import SystemSettingRepository
from app.repositories.translation import TranslationJobRepository
from app.services.limits import LimitService, _day_start
from app.settings.service import SettingsService


def _service(pb) -> LimitService:
    return LimitService(
        documents=DocumentRepository(pb),
        jobs=TranslationJobRepository(pb),
        settings=SettingsService(SystemSettingRepository(pb)),
        fallback_upload_bytes=1000,
    )


def _setting(fake_pb, key: str, value: object, type_: str) -> None:
    fake_pb.seed("system_settings", {"key": key, "value": value, "type": type_})


async def test_unlimited_by_default(pb, fake_pb) -> None:
    limits = await _service(pb).limits()
    assert limits.uploads_per_day is None
    assert limits.jobs_per_day is None
    # No daily cap: the check passes even with many existing records.
    await _service(pb).check_upload("w1")


async def test_upload_file_size_uses_product_setting(pb, fake_pb) -> None:
    _setting(fake_pb, "upload.maximum_file_size", 500, "int")
    service = _service(pb)
    with pytest.raises(UsageLimitError):
        await service.check_file_size(501)
    await service.check_file_size(500)


async def test_daily_upload_limit_enforced(pb, fake_pb) -> None:
    _setting(fake_pb, "limits.uploads_per_day", 1, "int")
    fake_pb.seed(
        "documents",
        {"workspace": "w1", "created": f"{_day_start()[:10]} 10:00:00Z", "status": "ready"},
    )
    with pytest.raises(UsageLimitError):
        await _service(pb).check_upload("w1")


async def test_concurrent_job_limit_enforced(pb, fake_pb) -> None:
    _setting(fake_pb, "limits.max_concurrent_jobs_per_user", 1, "int")
    fake_pb.seed("translation_jobs", {"workspace": "w1", "status": "translating"})
    with pytest.raises(UsageLimitError):
        await _service(pb).check_job_create("w1")


async def test_other_workspace_does_not_count(pb, fake_pb) -> None:
    _setting(fake_pb, "limits.uploads_per_day", 1, "int")
    fake_pb.seed(
        "documents",
        {"workspace": "w2", "created": f"{_day_start()[:10]} 10:00:00Z", "status": "ready"},
    )
    await _service(pb).check_upload("w1")


async def test_retry_cap(pb, fake_pb) -> None:
    _setting(fake_pb, "limits.retries_per_job", 2, "int")
    job = fake_pb.seed(
        "translation_jobs",
        {
            "workspace": "w1",
            "document": "d1",
            "target_language": "fa",
            "status": "failed",
            "metadata": {"retry_count": 2},
        },
    )
    from app.repositories.translation import TranslationJobRepository as Jobs

    record = await Jobs(pb).get(job["id"])
    with pytest.raises(UsageLimitError):
        await _service(pb).check_retry(record)
