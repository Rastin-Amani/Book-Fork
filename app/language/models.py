"""Language domain model.

Language behaviour is **data-driven**. Direction, script, and identifiers come
from records/registry data — there is no hardcoded RTL/LTR list in code.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable


class Direction(StrEnum):
    LTR = "ltr"
    RTL = "rtl"


@dataclass(frozen=True, slots=True)
class Language:
    """A language entry, typically loaded from the language registry."""

    tag: str  # BCP-47, e.g. "en-US", "pt-BR", "fa"
    name: str  # English display name
    direction: Direction
    native_name: str | None = None
    script: str | None = None  # ISO 15924, e.g. "Latn", "Arab", "Cyrl"
    region: str | None = None
    iso639_1: str | None = None
    iso639_3: str | None = None
    family: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def is_rtl(self) -> bool:
        """Whether this language is right-to-left, from its data (not a list)."""
        return self.direction is Direction.RTL


@runtime_checkable
class LanguageRegistry(Protocol):
    """Read access to the configured languages."""

    async def resolve(self, tag: str) -> Language | None:
        """Resolve a BCP-47/ISO tag to a language, or None if unknown."""
        ...

    async def list(self) -> Sequence[Language]:
        """Return all configured languages."""
        ...
