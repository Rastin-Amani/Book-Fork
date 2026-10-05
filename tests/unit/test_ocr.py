"""OCR abstraction: optional, never mandatory."""

from __future__ import annotations

import pytest
from app.documents.ocr.base import NullOcrProvider, OcrStatus, build_ocr_provider
from app.exceptions import ConfigurationError, OcrUnavailableError


async def test_null_provider_reports_unavailable() -> None:
    provider = NullOcrProvider()
    with pytest.raises(OcrUnavailableError):
        await provider.recognize(b"image-bytes", language_hint="fa")


def test_build_none_provider() -> None:
    provider = build_ocr_provider("none")
    assert provider.name == "none"
    assert build_ocr_provider(None).name == "none"


def test_unknown_provider_is_configuration_error() -> None:
    with pytest.raises(ConfigurationError):
        build_ocr_provider("tesseract")


def test_status_values_are_clean_and_explicit() -> None:
    assert OcrStatus.REQUIRED.value == "ocr_required"
    assert OcrStatus.UNAVAILABLE.value == "ocr_unavailable"
    assert OcrStatus.COMPLETED.value == "ocr_completed"
