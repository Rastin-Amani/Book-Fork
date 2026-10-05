"""Language registry records (data-driven language and locale metadata)."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from app.schemas.base import Record


class LanguageRecord(Record):
    language_code: str
    name: str
    direction: str
    iso_639_1: str | None = None
    iso_639_3: str | None = None
    native_name: str | None = None
    bcp47_prefix: str | None = None
    script_code: str | None = None
    default_locale: str | None = None
    enabled: bool = True
    popular: bool = False
    sort_order: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class LanguageVariant(Record):
    language: str
    locale: str
    script_code: str | None = None
    direction: str | None = None
    name: str | None = None
    native_name: str | None = None
    normalization_pipeline: dict[str, Any] = Field(default_factory=dict)
    segmentation_strategy: dict[str, Any] = Field(default_factory=dict)
    punctuation_profile: dict[str, Any] = Field(default_factory=dict)
    quotation_profile: dict[str, Any] = Field(default_factory=dict)
    formatting_profile: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
