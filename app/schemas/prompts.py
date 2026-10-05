"""Prompt template and version domain records."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field

from app.schemas.base import Record


class PromptPurpose(StrEnum):
    TRANSLATION = "translation"
    DETECTION = "detection"
    QA = "qa"
    GLOSSARY = "glossary"
    OTHER = "other"


class PromptStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class PromptTemplate(Record):
    name: str
    slug: str
    purpose: PromptPurpose
    description: str | None = None
    workspace: str | None = None
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class PromptVersion(Record):
    template: str
    version: int
    body: str
    status: PromptStatus
    variables: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = None
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
