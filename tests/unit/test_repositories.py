"""Typed repository CRUD, filtering, and filter escaping."""

from __future__ import annotations

import pytest
from app.exceptions import NotFoundError
from app.repositories.languages import LanguageRepository
from app.repositories.settings import SystemSettingRepository


async def test_crud_roundtrip(pb) -> None:
    repo = LanguageRepository(pb)
    created = await repo.create(
        {"language_code": "xx", "name": "Test", "direction": "ltr", "enabled": True}
    )
    assert created.id

    fetched = await repo.get(created.id)
    assert fetched.language_code == "xx"

    updated = await repo.update(created.id, {"name": "Renamed"})
    assert updated.name == "Renamed"

    await repo.delete(created.id)
    with pytest.raises(NotFoundError):
        await repo.get(created.id)


async def test_filter_and_sort(pb, fake_pb) -> None:
    repo = SystemSettingRepository(pb)
    fake_pb.seed("system_settings", {"key": "b.two", "value": 2, "type": "int", "category": "jobs"})
    fake_pb.seed(
        "system_settings", {"key": "a.one", "value": 1, "type": "int", "category": "upload"}
    )

    all_settings = await repo.list_all(sort="key")
    assert [s.key for s in all_settings] == ["a.one", "b.two"]

    jobs = await repo.list_by_category("jobs")
    assert [s.key for s in jobs] == ["b.two"]


async def test_filter_value_is_escaped(pb) -> None:
    repo = LanguageRepository(pb)
    tricky = 'en"-x'
    await repo.create({"language_code": tricky, "name": "Tricky", "direction": "ltr"})
    found = await repo.get_by_code(tricky)
    assert found is not None
    assert found.language_code == tricky


async def test_missing_returns_none(pb) -> None:
    repo = LanguageRepository(pb)
    assert await repo.get_by_code("does-not-exist") is None


async def test_list_all_pages_past_the_per_request_cap(pb, fake_pb) -> None:
    repo = LanguageRepository(pb)
    for i in range(5):
        fake_pb.seed(
            "languages",
            {"language_code": f"x{i}", "name": f"L{i}", "direction": "ltr", "enabled": True},
        )

    page = await repo.list(per_page=2)
    assert len(page) == 2  # list() stays single-page

    everything = await repo.list_all(per_page=2)
    assert sorted(item.language_code for item in everything) == ["x0", "x1", "x2", "x3", "x4"]


def test_empty_string_unset_fields_become_defaults() -> None:
    # PocketBase serializes unset fields as "" (not null). Unset dates must not
    # reach the model as datetimes (reads 500), and unset relations/optional
    # text must become None so `is None` fallbacks work.
    from app.repositories.translation import TranslationJobRepository
    from app.schemas.pocketbase import PocketBaseRecord

    repo = TranslationJobRepository.__new__(TranslationJobRepository)
    record = PocketBaseRecord.model_validate(
        {
            "id": "j1",
            "workspace": "w1",
            "document": "d1",
            "target_language": "fa",  # required text: "" would be kept as-is
            "status": "queued",
            "started_at": "",
            "completed_at": "",
            "cancelled_at": "",
            "lease_expires_at": "",
            "last_heartbeat": "",
            "source_language": "",  # optional text -> None
            "provider_connection": "",  # unset relation -> None
        }
    )
    job = repo._to_model(record)
    assert job.started_at is None
    assert job.completed_at is None
    assert job.source_language is None
    assert job.provider_connection is None
    assert job.target_language == "fa"
