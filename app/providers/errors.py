"""Normalized provider error taxonomy.

Provider failures are mapped into application-level categories so the retry
policy can distinguish transient from permanent failures. Permanent errors
(authentication, invalid request, invalid response, context too large) are never
retried indefinitely.
"""

from __future__ import annotations

from enum import StrEnum

from app.exceptions import BookForkError


class ProviderErrorCategory(StrEnum):
    AUTHENTICATION = "authentication_error"
    INVALID_REQUEST = "invalid_request"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    UNAVAILABLE = "provider_unavailable"
    CONTEXT_TOO_LARGE = "context_too_large"
    INVALID_RESPONSE = "invalid_response"
    UNKNOWN = "unknown_provider_error"


_PERMANENT = frozenset(
    {
        ProviderErrorCategory.AUTHENTICATION,
        ProviderErrorCategory.INVALID_REQUEST,
        ProviderErrorCategory.CONTEXT_TOO_LARGE,
        ProviderErrorCategory.INVALID_RESPONSE,
    }
)

# Provider categories mapped to stable application error codes so the worker and
# API surface machine-readable codes without leaking vendor detail.
_APP_CODE: dict[ProviderErrorCategory, str] = {
    ProviderErrorCategory.AUTHENTICATION: "PROVIDER_AUTH_FAILED",
    ProviderErrorCategory.INVALID_REQUEST: "PROVIDER_INVALID_REQUEST",
    ProviderErrorCategory.RATE_LIMITED: "PROVIDER_RATE_LIMITED",
    ProviderErrorCategory.TIMEOUT: "PROVIDER_TIMEOUT",
    ProviderErrorCategory.UNAVAILABLE: "PROVIDER_UNAVAILABLE",
    ProviderErrorCategory.CONTEXT_TOO_LARGE: "PROVIDER_CONTEXT_TOO_LARGE",
    ProviderErrorCategory.INVALID_RESPONSE: "PROVIDER_INVALID_RESPONSE",
    ProviderErrorCategory.UNKNOWN: "PROVIDER_ERROR",
}


class ProviderError(BookForkError):
    status_code = 502
    code = "PROVIDER_ERROR"

    def __init__(
        self,
        category: ProviderErrorCategory,
        message: str | None = None,
        *,
        retryable: bool | None = None,
    ) -> None:
        self.category = category
        self.code = _APP_CODE.get(category, "PROVIDER_ERROR")
        self.retryable = (category not in _PERMANENT) if retryable is None else retryable
        super().__init__(message or category.value)


def classify_http_status(status: int) -> ProviderErrorCategory:
    if status in (401, 403):
        return ProviderErrorCategory.AUTHENTICATION
    if status == 400:
        return ProviderErrorCategory.INVALID_REQUEST
    if status == 404:
        return ProviderErrorCategory.INVALID_REQUEST
    if status == 408:
        return ProviderErrorCategory.TIMEOUT
    if status == 413:
        return ProviderErrorCategory.CONTEXT_TOO_LARGE
    if status == 429:
        return ProviderErrorCategory.RATE_LIMITED
    if status >= 500:
        return ProviderErrorCategory.UNAVAILABLE
    return ProviderErrorCategory.UNKNOWN


# Substrings that mean "try again", even when an upstream gateway wraps them in
# a 4xx (the 9 Router gateway returns HTTP 400 for a transient
# ``server_error: Model is unavailable``). Only applied to otherwise-permanent
# client errors, never to authentication failures.
_TRANSIENT_MARKERS = (
    "server_error",
    "upstream request failed",
    "model is unavailable",
    "unavailable",
    "overloaded",
    "temporarily",
    "try again",
    "capacity",
    "timed out",
    "timeout",
    "rate limit",
    "too many requests",
)

_TRANSIENT_SCAN_CHARS = 2000


def classify_error_response(status: int, body: str = "") -> ProviderErrorCategory:
    """Classify an error response, honoring a transient signal inside the body.

    Some OpenAI-compatible gateways answer with HTTP 400 while the body says the
    *upstream* failed (model unavailable, overloaded, …). Treating that as a
    permanent bad request means a transient outage permanently fails segments.
    """
    category = classify_http_status(status)
    if category is ProviderErrorCategory.INVALID_REQUEST and _looks_transient(body):
        return ProviderErrorCategory.UNAVAILABLE
    return category


def _looks_transient(body: str) -> bool:
    lowered = (body or "")[:_TRANSIENT_SCAN_CHARS].lower()
    return any(marker in lowered for marker in _TRANSIENT_MARKERS)
