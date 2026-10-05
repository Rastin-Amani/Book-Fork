"""PocketBase-backed language registry.

Implements the ``LanguageRegistry`` protocol. Language metadata (direction,
script, names) is read from data and derived from CLDR; nothing is hardcoded.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.exceptions import ValidationError
from app.language.models import Direction, Language
from app.language.normalize import NormalizedLanguage, normalize_tag
from app.repositories.languages import LanguageRepository
from app.schemas.languages import LanguageRecord


def _record_to_language(record: LanguageRecord, normalized: NormalizedLanguage) -> Language:
    try:
        direction = Direction(record.direction)
    except ValueError:
        direction = normalized.direction
    return Language(
        tag=record.default_locale or record.language_code,
        name=record.name or normalized.name,
        direction=direction,
        native_name=record.native_name or normalized.native_name,
        script=record.script_code or normalized.script,
        region=normalized.region,
        iso639_1=record.iso_639_1 or normalized.iso_639_1,
        iso639_3=record.iso_639_3 or normalized.iso_639_3,
        family=record.metadata.get("family"),
        metadata=dict(record.metadata),
    )


class PocketBaseLanguageRegistry:
    """Read access to configured languages and variants."""

    def __init__(self, languages: LanguageRepository, *, token: str | None = None) -> None:
        self._languages = languages
        self._token = token

    async def resolve(self, tag: str) -> Language | None:
        try:
            normalized = normalize_tag(tag)
        except ValidationError:
            return None
        record = await self._languages.get_by_code(normalized.language, token=self._token)
        if record is None:
            record = await self._languages.get_by_code(normalized.tag, token=self._token)
        if record is None:
            return None
        return _record_to_language(record, normalized)

    async def list(self) -> Sequence[Language]:
        records = await self._languages.list_enabled(token=self._token)
        languages: list[Language] = []
        for record in records:
            try:
                normalized = normalize_tag(record.default_locale or record.language_code)
            except ValidationError:
                continue
            languages.append(_record_to_language(record, normalized))
        return languages

    async def enabled_codes(self) -> Sequence[str]:
        """Enabled language codes, for constraining detection candidates."""
        records = await self._languages.list_enabled(token=self._token)
        return [record.language_code for record in records]
