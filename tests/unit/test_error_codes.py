"""Stable application error codes and provider error mapping."""

from __future__ import annotations

from app.exceptions import (
    BookForkError,
    DocumentCorruptedError,
    DocumentTooLargeError,
    DocumentUnsupportedError,
    InsufficientCreditsError,
    LanguageUnsupportedError,
    ModelUnsupportedError,
    OutputGenerationFailedError,
    ProviderAuthFailedError,
    ProviderRateLimitedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    TranslationValidationFailedError,
    UsageLimitError,
)
from app.providers.errors import ProviderError, ProviderErrorCategory


def test_domain_error_codes_are_stable() -> None:
    assert DocumentUnsupportedError().code == "DOCUMENT_UNSUPPORTED"
    assert DocumentCorruptedError().code == "DOCUMENT_CORRUPTED"
    assert DocumentTooLargeError().code == "DOCUMENT_TOO_LARGE"
    assert DocumentTooLargeError().status_code == 413
    assert LanguageUnsupportedError().code == "LANGUAGE_UNSUPPORTED"
    assert ModelUnsupportedError().code == "MODEL_UNSUPPORTED"
    assert ProviderAuthFailedError().code == "PROVIDER_AUTH_FAILED"
    assert ProviderRateLimitedError().code == "PROVIDER_RATE_LIMITED"
    assert ProviderTimeoutError().code == "PROVIDER_TIMEOUT"
    assert ProviderUnavailableError().code == "PROVIDER_UNAVAILABLE"
    assert TranslationValidationFailedError().code == "TRANSLATION_VALIDATION_FAILED"
    assert OutputGenerationFailedError().code == "OUTPUT_GENERATION_FAILED"
    assert InsufficientCreditsError().code == "INSUFFICIENT_CREDITS"
    assert InsufficientCreditsError().status_code == 402
    assert UsageLimitError().status_code == 429


def test_all_domain_errors_are_book_fork_errors() -> None:
    for error in (
        DocumentUnsupportedError,
        DocumentCorruptedError,
        DocumentTooLargeError,
        LanguageUnsupportedError,
        ModelUnsupportedError,
        ProviderAuthFailedError,
        ProviderRateLimitedError,
        ProviderTimeoutError,
        ProviderUnavailableError,
        TranslationValidationFailedError,
        OutputGenerationFailedError,
        InsufficientCreditsError,
        UsageLimitError,
    ):
        assert issubclass(error, BookForkError)
        assert error().status_code >= 400
        assert error().code.isupper()


def test_provider_error_maps_category_to_code() -> None:
    assert ProviderError(ProviderErrorCategory.AUTHENTICATION).code == "PROVIDER_AUTH_FAILED"
    assert ProviderError(ProviderErrorCategory.RATE_LIMITED).code == "PROVIDER_RATE_LIMITED"
    assert ProviderError(ProviderErrorCategory.TIMEOUT).code == "PROVIDER_TIMEOUT"
    assert ProviderError(ProviderErrorCategory.UNAVAILABLE).code == "PROVIDER_UNAVAILABLE"
    permanent = ProviderError(ProviderErrorCategory.AUTHENTICATION)
    assert permanent.retryable is False
    transient = ProviderError(ProviderErrorCategory.RATE_LIMITED)
    assert transient.retryable is True
