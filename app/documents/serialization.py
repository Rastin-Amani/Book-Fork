"""Versioned canonical-document serialization.

The canonical tree can be large, so it is stored as an object (not inside a
PocketBase record) under a deterministic storage key.
"""

from __future__ import annotations

from app.documents.model import CANONICAL_MODEL_VERSION, CanonicalDocument
from app.exceptions import ValidationError


def to_json_bytes(document: CanonicalDocument) -> bytes:
    return document.model_dump_json().encode("utf-8")


def from_json_bytes(data: bytes) -> CanonicalDocument:
    try:
        document = CanonicalDocument.model_validate_json(data)
    except ValueError as exc:
        raise ValidationError("Canonical document payload is invalid.") from exc
    if document.canonical_model_version != CANONICAL_MODEL_VERSION:
        raise ValidationError(
            f"Unsupported canonical model version {document.canonical_model_version}."
        )
    return document


def canonical_storage_key(document_id: str, *, version: int = CANONICAL_MODEL_VERSION) -> str:
    """Deterministic storage key for a document's canonical tree."""
    safe_id = document_id.strip()
    if not safe_id:
        raise ValidationError("A document id is required.")
    return f"documents/{safe_id}/canonical/v{version}.json"
