"""Language registry repositories."""

from __future__ import annotations

from app.repositories.base import PocketBaseRepository, filter_eq
from app.schemas.languages import LanguageRecord, LanguageVariant


class LanguageRepository(PocketBaseRepository[LanguageRecord]):
    collection = "languages"
    model = LanguageRecord

    async def get_by_code(self, code: str, *, token: str | None = None) -> LanguageRecord | None:
        return await self.first(filter=filter_eq("language_code", code), token=token)

    async def list_enabled(self, *, token: str | None = None) -> list[LanguageRecord]:
        return await self.list(filter="enabled = true", sort="sort_order", token=token)


class LanguageVariantRepository(PocketBaseRepository[LanguageVariant]):
    collection = "language_variants"
    model = LanguageVariant

    async def get_for_language(
        self, language_id: str, locale: str, *, token: str | None = None
    ) -> LanguageVariant | None:
        clause = f'language = "{language_id}" && locale = "{locale}"'
        return await self.first(filter=clause, token=token)

    async def list_for_language(
        self, language_id: str, *, token: str | None = None
    ) -> list[LanguageVariant]:
        return await self.list(filter=filter_eq("language", language_id), token=token)
