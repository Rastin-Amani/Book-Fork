"""Typed system settings service.

Settings are stored as ``value`` + ``type`` records; the type drives
deserialization so business defaults never live in Python.
"""

from __future__ import annotations

from typing import Any

from app.exceptions import ConfigurationError, NotFoundError
from app.repositories.settings import SystemSettingRepository
from app.schemas.settings import SettingType, SystemSetting


def coerce_value(setting: SystemSetting) -> Any:
    """Deserialize a setting's raw JSON value according to its declared type."""
    value = setting.value
    try:
        if setting.type is SettingType.BOOL:
            return bool(value)
        if setting.type is SettingType.INT:
            return int(value)
        if setting.type is SettingType.FLOAT:
            return float(value)
        if setting.type is SettingType.STRING:
            return str(value)
        return value
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"Setting {setting.key!r} is not a valid {setting.type}.") from exc


class SettingsService:
    """Reads typed settings from the database."""

    def __init__(self, repository: SystemSettingRepository, *, token: str | None = None) -> None:
        self._repository = repository
        self._token = token

    async def get(self, key: str, default: Any = None) -> Any:
        setting = await self._repository.get_by_key(key, token=self._token)
        if setting is None:
            return default
        return coerce_value(setting)

    async def require(self, key: str) -> Any:
        setting = await self._repository.get_by_key(key, token=self._token)
        if setting is None:
            raise NotFoundError(f"Required setting {key!r} is not configured.")
        return coerce_value(setting)

    async def all(self) -> dict[str, Any]:
        settings = await self._repository.list_all(sort="key", token=self._token)
        return {setting.key: coerce_value(setting) for setting in settings}
