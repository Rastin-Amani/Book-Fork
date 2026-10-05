"""OCR abstraction.

OCR is optional and never mandatory: the document pipeline records
``ocr_required`` for scanned pages and fails cleanly with ``ocr_unavailable`` if
no provider is configured. Concrete providers (tesseract, paddleocr, cloud) can
be added behind this interface without touching the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from app.exceptions import ConfigurationError, OcrUnavailableError


class OcrStatus(StrEnum):
    COMPLETED = "ocr_completed"
    REQUIRED = "ocr_required"
    UNAVAILABLE = "ocr_unavailable"


@dataclass(frozen=True, slots=True)
class OcrResult:
    text: str
    confidence: float | None = None
    status: OcrStatus = OcrStatus.COMPLETED
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class OcrProvider(Protocol):
    name: str

    async def recognize(self, image: bytes, *, language_hint: str | None = None) -> OcrResult:
        """Recognize text in a single page image."""
        ...


class NullOcrProvider:
    """Default provider: reports OCR as unavailable."""

    name = "none"

    async def recognize(self, image: bytes, *, language_hint: str | None = None) -> OcrResult:
        raise OcrUnavailableError()


def build_ocr_provider(name: str | None) -> OcrProvider:
    """Construct an OCR provider from configuration.

    Only the null provider ships today; other names are configuration errors
    rather than silent fallbacks.
    """
    if name in (None, "", "none", "null"):
        return NullOcrProvider()
    raise ConfigurationError(f"OCR provider {name!r} is not available in this deployment.")
