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
    """Reads typed settings from the database.

    Settings are a small, global collection. Resolving them one key per
    PocketBase round trip turned a single estimate into ~18 serial network
    calls, so the first ``get`` loads the collection once and indexes it. The
    cache lives on the service instance, which is per request (web) or built
    once at startup (worker), so it never spans requests or hides writes made
    through a different service.
    """

    def __init__(self, repository: SystemSettingRepository, *, token: str | None = None) -> None:
        self._repository = repository
        self._token = token
        self._cache: dict[str, Any] | None = None

    async def _values(self) -> dict[str, Any]:
        if self._cache is None:
            settings = await self._repository.list_all(sort="key", token=self._token)
            self._cache = {setting.key: coerce_value(setting) for setting in settings}
        return self._cache

    async def get(self, key: str, default: Any = None) -> Any:
        return (await self._values()).get(key, default)

    async def require(self, key: str) -> Any:
        values = await self._values()
        if key not in values:
            raise NotFoundError(f"Required setting {key!r} is not configured.")
        return values[key]

    async def all(self) -> dict[str, Any]:
        return dict(await self._values())
