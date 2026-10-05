"""System settings repository."""

from __future__ import annotations

from app.repositories.base import PocketBaseRepository, filter_eq
from app.schemas.settings import SystemSetting


class SystemSettingRepository(PocketBaseRepository[SystemSetting]):
    collection = "system_settings"
    model = SystemSetting

    async def get_by_key(self, key: str, *, token: str | None = None) -> SystemSetting | None:
        return await self.first(filter=filter_eq("key", key), token=token)

    async def list_by_category(
        self, category: str, *, token: str | None = None
    ) -> list[SystemSetting]:
        return await self.list(filter=filter_eq("category", category), sort="key", token=token)
