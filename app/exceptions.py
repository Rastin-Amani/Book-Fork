"""Application exception taxonomy.

Domain code raises these; the API layer maps them to HTTP responses. This keeps
business code free of HTTP concerns and keeps HTTP status semantics honest.
"""

from __future__ import annotations


class BookForkError(Exception):
    """Base class for all expected, handled application errors."""

    status_code: int = 500
    code: str = "internal_error"
    message: str = "An unexpected error occurred."

    def __init__(self, message: str | None = None) -> None:
        if message is not None:
            self.message = message
        super().__init__(self.message)


class ValidationError(BookForkError):
    status_code = 422
    code = "validation_error"
    message = "The submitted data is invalid."


class AuthenticationError(BookForkError):
    status_code = 401
    code = "authentication_required"
    message = "Authentication is required."


class PermissionDeniedError(BookForkError):
    status_code = 403
    code = "permission_denied"
    message = "You do not have permission to perform this action."


class NotFoundError(BookForkError):
    status_code = 404
    code = "not_found"
    message = "The requested resource was not found."


class ConflictError(BookForkError):
    status_code = 409
    code = "conflict"
    message = "The request conflicts with the current state."


class RateLimitedError(BookForkError):
    status_code = 429
    code = "rate_limited"
    message = "Too many requests. Please try again later."


class ConfigurationError(BookForkError):
    status_code = 500
    code = "configuration_error"
    message = "The application is misconfigured."


class PromptRenderError(BookForkError):
    status_code = 422
    code = "prompt_render_error"
    message = "The prompt template could not be rendered."


class OcrUnavailableError(BookForkError):
    status_code = 422
    code = "ocr_unavailable"
    message = "This document requires OCR, but no OCR provider is configured."


class UpstreamError(BookForkError):
    """An external dependency (PocketBase, LLM provider, storage) failed."""

    status_code = 502
    code = "upstream_error"
    message = "An upstream service failed."


# ---------------------------------------------------------------------------
# Stable, machine-readable application error codes (Phase 8).
#
# These are surfaced to clients (safe human message + code) while the technical
# detail stays in logs. New codes should be added here, never inlined as bare
# strings at raise sites.
# ---------------------------------------------------------------------------


class DocumentUnsupportedError(BookForkError):
    status_code = 422
    code = "DOCUMENT_UNSUPPORTED"
    message = "This document type is not supported."


class DocumentCorruptedError(BookForkError):
    status_code = 422
    code = "DOCUMENT_CORRUPTED"
    message = "The document could not be read."


class DocumentTooLargeError(BookForkError):
    status_code = 413
    code = "DOCUMENT_TOO_LARGE"
    message = "The document exceeds the allowed size."


class LanguageUnsupportedError(BookForkError):
    status_code = 422
    code = "LANGUAGE_UNSUPPORTED"
    message = "This language is not supported."


class ModelUnsupportedError(BookForkError):
    status_code = 422
    code = "MODEL_UNSUPPORTED"
    message = "No configured model supports this language pair."


class ProviderAuthFailedError(BookForkError):
    status_code = 502
    code = "PROVIDER_AUTH_FAILED"
    message = "The provider rejected the credentials."


class ProviderRateLimitedError(BookForkError):
    status_code = 503
    code = "PROVIDER_RATE_LIMITED"
    message = "The provider is rate limiting requests."


class ProviderTimeoutError(BookForkError):
    status_code = 504
    code = "PROVIDER_TIMEOUT"
    message = "The provider did not respond in time."


class ProviderUnavailableError(BookForkError):
    status_code = 502
    code = "PROVIDER_UNAVAILABLE"
    message = "The provider is unavailable."


class TranslationValidationFailedError(BookForkError):
    status_code = 422
    code = "TRANSLATION_VALIDATION_FAILED"
    message = "The translation failed validation."


class OutputGenerationFailedError(BookForkError):
    status_code = 500
    code = "OUTPUT_GENERATION_FAILED"
    message = "The translated document could not be generated."


class InsufficientCreditsError(BookForkError):
    status_code = 402
    code = "INSUFFICIENT_CREDITS"
    message = "There are not enough credits to perform this action."


class UsageLimitError(BookForkError):
    status_code = 429
    code = "USAGE_LIMIT_EXCEEDED"
    message = "You have reached a configured usage limit."


