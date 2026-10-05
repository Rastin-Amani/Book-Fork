"""Structured translation output: schema, parsing and coverage validation.

The response schema is generated from Pydantic models (never hand-written), and
ordering is never trusted — every requested segment must appear exactly once.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as PydanticValidationError

from app.providers.errors import ProviderError, ProviderErrorCategory

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
# The prompt renders segments as ``[[idi]] text``; models that ignore the JSON
# response_format echo that same shape, so accept it as a fallback.
_SEGMENT_MARKER = re.compile(r"\[\[([^\[\]]+)\]\]")
_SNIPPET_CHARS = 400


def _snippet(text: str) -> str:
    text = (text or "").strip()
    return text if len(text) <= _SNIPPET_CHARS else text[:_SNIPPET_CHARS] + "…"


class TranslationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str
    translation: str


class TranslationBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    translations: list[TranslationItem]


def response_json_schema() -> dict[str, Any]:
    """JSON schema for a translation batch, generated from the models."""
    return TranslationBatch.model_json_schema()


def parse_translation_items(content: str) -> list[TranslationItem]:
    """Parse a provider response into items, tolerating code fences and wrappers."""
    if not content or not content.strip():
        raise ProviderError(ProviderErrorCategory.INVALID_RESPONSE, "Empty provider response.")

    text = content.strip()
    fenced = _JSON_FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()

    try:
        payload = _load_json(text)
    except ProviderError as exc:
        marked = _parse_marked_segments(text)
        if marked is not None:
            return marked
        raise ProviderError(
            ProviderErrorCategory.INVALID_RESPONSE,
            f"{exc.message} Offending content: {_snippet(text)}",
        ) from exc
    if isinstance(payload, dict) and "translations" in payload:
        raw_items = payload["translations"]
    elif isinstance(payload, list):
        raw_items = payload
    elif isinstance(payload, dict) and all(isinstance(v, str) for v in payload.values()):
        raw_items = [{"segment_id": key, "translation": value} for key, value in payload.items()]
    else:
        raise ProviderError(ProviderErrorCategory.INVALID_RESPONSE, "Unrecognized response shape.")

    try:
        batch = TranslationBatch.model_validate({"translations": raw_items})
    except PydanticValidationError as exc:
        raise ProviderError(ProviderErrorCategory.INVALID_RESPONSE) from exc
    return batch.translations


def _parse_marked_segments(text: str) -> list[TranslationItem] | None:
    """Parse ``[[segment_id]] translation`` markers, or None when absent."""
    markers = list(_SEGMENT_MARKER.finditer(text))
    if not markers:
        return None
    items: list[TranslationItem] = []
    for index, marker in enumerate(markers):
        start = marker.end()
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        translation = text[start:end].strip()
        items.append(TranslationItem(segment_id=marker.group(1).strip(), translation=translation))
    return items


def _load_json(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        # Fall back to the first balanced JSON object/array in the text.
        for opener, closer in (("{", "}"), ("[", "]")):
            start = text.find(opener)
            end = text.rfind(closer)
            if start != -1 and end > start:
                try:
                    return json.loads(text[start : end + 1])
                except ValueError:
                    continue
        raise ProviderError(
            ProviderErrorCategory.INVALID_RESPONSE, "Response is not JSON."
        ) from None


def map_translations(
    items: Sequence[TranslationItem],
    requested_ids: Sequence[str],
    *,
    strict: bool = True,
    tolerate_missing: bool = False,
) -> dict[str, str]:
    """Map items to a translation dict, enforcing exact one-to-one coverage.

    ``tolerate_missing`` lets a caller accept a partial batch: segments the model
    skipped or returned empty are simply left out so they can fail individually
    instead of failing every other segment in the batch, and a stray unknown id
    is ignored rather than failing the batch. Duplicate ids are always rejected.
    When ``tolerate_missing`` is false, unknown ids are rejected in strict mode.
    """
    requested = set(requested_ids)
    result: dict[str, str] = {}
    seen: set[str] = set()
    for item in items:
        segment_id = item.segment_id
        if segment_id in seen:
            raise ProviderError(
                ProviderErrorCategory.INVALID_RESPONSE, f"Duplicate segment id {segment_id!r}."
            )
        if segment_id not in requested:
            if tolerate_missing:
                # A model occasionally echoes a stray id; do not fail the whole
                # batch over it. The real segment will fail on its own below.
                continue
            if strict:
                raise ProviderError(
                    ProviderErrorCategory.INVALID_RESPONSE, f"Unknown segment id {segment_id!r}."
                )
            continue
        if not item.translation or not item.translation.strip():
            if tolerate_missing:
                continue
            raise ProviderError(
                ProviderErrorCategory.INVALID_RESPONSE,
                f"Empty translation for segment {segment_id!r}.",
            )
        seen.add(segment_id)
        result[segment_id] = item.translation

    missing = requested - seen
    if missing and strict and not tolerate_missing:
        raise ProviderError(
            ProviderErrorCategory.INVALID_RESPONSE,
            f"Missing translations for {len(missing)} segment(s).",
        )
    return result
