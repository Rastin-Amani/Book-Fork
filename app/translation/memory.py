"""Exact translation memory.

Matching is always language-pair scoped (never by source hash alone). Only
approved entries are reused, and reuse does not incur a provider call.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from app.repositories.knowledge import TranslationMemoryRepository
from app.schemas.knowledge import TranslationMemoryEntry

_WHITESPACE = re.compile(r"\s+")


def normalize_for_match(text: str) -> str:
    """Language-agnostic normalization for exact matching."""
    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = normalized.strip().lower()
    return _WHITESPACE.sub(" ", normalized)


def memory_hash(source_language: str, target_language: str, normalized_text: str) -> str:
    """Language-pair-scoped hash; never used without the pair context."""
    payload = f"{source_language}\x1f{target_language}\x1f{normalized_text}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class TranslationMemoryHit:
    entry_id: str
    translation: str
    quality: float | None = None


@runtime_checkable
class TranslationMemoryStore(Protocol):
    """Storage contract the engine depends on (concrete or in-memory)."""

    async def lookup(
        self, source_language: str, target_language: str, source_text: str
    ) -> TranslationMemoryHit | None: ...

    async def store(
        self,
        *,
        source_language: str,
        target_language: str,
        source_text: str,
        translation: str,
        approved: bool = False,
        quality: float | None = None,
        domain: str | None = None,
    ) -> Any: ...


class TranslationMemory:
    def __init__(
        self,
        repository: TranslationMemoryRepository,
        *,
        workspace_id: str | None = None,
        token: str | None = None,
    ) -> None:
        self._repository = repository
        self._workspace_id = workspace_id
        self._token = token
        # Approved entries for a language pair are fetched once and reused for
        # the whole job. Looking up one segment per PocketBase query used to
        # fire thousands of requests in a burst for a book-sized job and lose
        # the connection mid-job.
        self._cache: dict[tuple[str, str], dict[str, TranslationMemoryHit]] = {}

    async def _approved_index(
        self, source_language: str, target_language: str
    ) -> dict[str, TranslationMemoryHit]:
        key = (source_language, target_language)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        entries = await self._repository.list_approved(
            source_language,
            target_language,
            workspace_id=self._workspace_id,
            token=self._token,
        )
        best: dict[str, tuple[float, TranslationMemoryHit]] = {}
        for entry in entries:
            normalized = entry.normalized_source_text or normalize_for_match(entry.source_text)
            quality = entry.quality or 0.0
            current = best.get(normalized)
            if current is None or quality > current[0]:
                best[normalized] = (
                    quality,
                    TranslationMemoryHit(
                        entry_id=entry.id,
                        translation=entry.translation,
                        quality=entry.quality,
                    ),
                )
        index = {normalized: hit for normalized, (_, hit) in best.items()}
        self._cache[key] = index
        return index

    async def lookup(
        self, source_language: str, target_language: str, source_text: str
    ) -> TranslationMemoryHit | None:
        normalized = normalize_for_match(source_text)
        if not normalized:
            return None
        return (await self._approved_index(source_language, target_language)).get(normalized)

    async def store(
        self,
        *,
        source_language: str,
        target_language: str,
        source_text: str,
        translation: str,
        approved: bool = False,
        quality: float | None = None,
        domain: str | None = None,
    ) -> TranslationMemoryEntry:
        normalized = normalize_for_match(source_text)
        return await self._repository.create(
            {
                "workspace": self._workspace_id,
                "source_language": source_language,
                "target_language": target_language,
                "source_text": source_text,
                "normalized_source_text": normalized,
                "translation": translation,
                "approved": approved,
                "quality": quality,
                "domain": domain,
                "source_hash": memory_hash(source_language, target_language, normalized),
            },
            token=self._token,
        )
