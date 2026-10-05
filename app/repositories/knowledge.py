"""Glossary, glossary-term, and translation-memory repositories."""

from __future__ import annotations

from app.repositories.base import PocketBaseRepository, escape_filter_value, filter_eq
from app.schemas.knowledge import Glossary, GlossaryTerm, TranslationMemoryEntry


class GlossaryRepository(PocketBaseRepository[Glossary]):
    collection = "glossaries"
    model = Glossary

    async def list_for_workspace(
        self, workspace_id: str, *, token: str | None = None
    ) -> list[Glossary]:
        return await self.list(filter=filter_eq("workspace", workspace_id), token=token)


class GlossaryTermRepository(PocketBaseRepository[GlossaryTerm]):
    collection = "glossary_terms"
    model = GlossaryTerm

    async def list_for_pair(
        self,
        glossary_id: str,
        source_language: str,
        target_language: str,
        *,
        token: str | None = None,
    ) -> list[GlossaryTerm]:
        clause = (
            f'glossary = "{escape_filter_value(glossary_id)}"'
            f' && source_language = "{escape_filter_value(source_language)}"'
            f' && target_language = "{escape_filter_value(target_language)}"'
        )
        return await self.list(filter=clause, token=token)


class TranslationMemoryRepository(PocketBaseRepository[TranslationMemoryEntry]):
    collection = "translation_memory_entries"
    model = TranslationMemoryEntry

    async def list_for_workspace(
        self, workspace_id: str, *, token: str | None = None
    ) -> list[TranslationMemoryEntry]:
        clause = f'workspace = "" || workspace = "{escape_filter_value(workspace_id)}"'
        return await self.list(filter=clause, sort="-created", token=token)

    async def find_exact(
        self,
        source_language: str,
        target_language: str,
        normalized_source_text: str,
        *,
        workspace_id: str | None = None,
        token: str | None = None,
    ) -> list[TranslationMemoryEntry]:
        """Exact matches are always scoped to the language pair."""
        clause = (
            filter_eq("source_language", source_language)
            + " && "
            + filter_eq("target_language", target_language)
            + " && "
            + filter_eq("normalized_source_text", normalized_source_text)
        )
        workspace_clause = (
            f'workspace = "" || workspace = "{escape_filter_value(workspace_id)}"'
            if workspace_id
            else 'workspace = ""'
        )
        return await self.list(filter=f"{clause} && ({workspace_clause})", token=token)
