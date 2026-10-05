"""System settings domain records (typed, configuration-driven)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field

from app.schemas.base import Record


class SettingType(StrEnum):
    STRING = "string"
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    JSON = "json"


class SystemSetting(Record):
    key: str
    value: Any = None
    type: SettingType
    description: str | None = None
    category: str | None = None
    editable: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
