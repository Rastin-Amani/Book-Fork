"""Glossary and translation-memory domain records."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from app.schemas.base import Record


class Glossary(Record):
    workspace: str
    name: str
    description: str | None = None
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class GlossaryTerm(Record):
    glossary: str
    source_language: str
    target_language: str
    source_term: str
    target_term: str
    case_sensitive: bool = False
    exact_match: bool = False
    preferred: bool = False
    forbidden: bool = False
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TranslationMemoryEntry(Record):
    source_language: str
    target_language: str
    source_text: str
    normalized_source_text: str
    translation: str
    workspace: str | None = None
    source_locale: str | None = None
    target_locale: str | None = None
    domain: str | None = None
    quality: float | None = None
    approved: bool = False
    source_hash: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
