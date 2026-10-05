"""Typed system settings resolution."""

from __future__ import annotations

import pytest
from app.exceptions import ConfigurationError, NotFoundError
from app.repositories.settings import SystemSettingRepository
from app.settings.service import SettingsService


async def test_typed_values(pb, fake_pb) -> None:
    fake_pb.seed("system_settings", {"key": "a.int", "value": 5, "type": "int"})
    fake_pb.seed("system_settings", {"key": "a.float", "value": 1.5, "type": "float"})
    fake_pb.seed("system_settings", {"key": "a.bool", "value": True, "type": "bool"})
    fake_pb.seed("system_settings", {"key": "a.string", "value": "hi", "type": "string"})
    fake_pb.seed("system_settings", {"key": "a.json", "value": [1, 2], "type": "json"})

    service = SettingsService(SystemSettingRepository(pb))
    assert await service.get("a.int") == 5
    assert await service.get("a.float") == 1.5
    assert await service.get("a.bool") is True
    assert await service.get("a.string") == "hi"
    assert await service.get("a.json") == [1, 2]


async def test_missing_returns_default(pb) -> None:
    service = SettingsService(SystemSettingRepository(pb))
    assert await service.get("nope", default=42) == 42


async def test_require_missing_raises(pb) -> None:
    service = SettingsService(SystemSettingRepository(pb))
    with pytest.raises(NotFoundError):
        await service.require("nope")


async def test_invalid_value_for_type_raises(pb, fake_pb) -> None:
    fake_pb.seed("system_settings", {"key": "bad", "value": "not-an-int", "type": "int"})
    service = SettingsService(SystemSettingRepository(pb))
    with pytest.raises(ConfigurationError):
        await service.get("bad")
