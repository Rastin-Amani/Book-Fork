"""Prompt template and version repositories."""

from __future__ import annotations

from app.repositories.base import PocketBaseRepository, escape_filter_value, filter_eq
from app.schemas.prompts import PromptTemplate, PromptVersion


class PromptTemplateRepository(PocketBaseRepository[PromptTemplate]):
    collection = "prompt_templates"
    model = PromptTemplate

    async def get_by_slug(self, slug: str, *, token: str | None = None) -> PromptTemplate | None:
        return await self.first(filter=filter_eq("slug", slug), token=token)


class PromptVersionRepository(PocketBaseRepository[PromptVersion]):
    collection = "prompt_versions"
    model = PromptVersion

    async def get_active(
        self, template_id: str, *, token: str | None = None
    ) -> PromptVersion | None:
        clause = f'template = "{escape_filter_value(template_id)}" && status = "active"'
        return await self.first(filter=clause, sort="-version", token=token)

    async def list_for_template(
        self, template_id: str, *, token: str | None = None
    ) -> list[PromptVersion]:
        return await self.list(
            filter=filter_eq("template", template_id), sort="-version", token=token
        )

    async def next_version_number(self, template_id: str, *, token: str | None = None) -> int:
        latest = await self.first(
            filter=filter_eq("template", template_id), sort="-version", token=token
        )
        return (latest.version + 1) if latest else 1
