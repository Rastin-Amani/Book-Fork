"""Provider error taxonomy and retryability."""

from __future__ import annotations

import pytest
from app.providers.errors import (
    ProviderError,
    ProviderErrorCategory,
    classify_error_response,
    classify_http_status,
)


@pytest.mark.parametrize(
    ("status", "category"),
    [
        (401, ProviderErrorCategory.AUTHENTICATION),
        (403, ProviderErrorCategory.AUTHENTICATION),
        (400, ProviderErrorCategory.INVALID_REQUEST),
        (413, ProviderErrorCategory.CONTEXT_TOO_LARGE),
        (429, ProviderErrorCategory.RATE_LIMITED),
        (408, ProviderErrorCategory.TIMEOUT),
        (500, ProviderErrorCategory.UNAVAILABLE),
        (418, ProviderErrorCategory.UNKNOWN),
    ],
)
def test_classify_status(status: int, category: ProviderErrorCategory) -> None:
    assert classify_http_status(status) is category


@pytest.mark.parametrize(
    ("category", "retryable"),
    [
        (ProviderErrorCategory.AUTHENTICATION, False),
        (ProviderErrorCategory.INVALID_REQUEST, False),
        (ProviderErrorCategory.CONTEXT_TOO_LARGE, False),
        (ProviderErrorCategory.INVALID_RESPONSE, False),
        (ProviderErrorCategory.RATE_LIMITED, True),
        (ProviderErrorCategory.TIMEOUT, True),
        (ProviderErrorCategory.UNAVAILABLE, True),
        (ProviderErrorCategory.UNKNOWN, True),
    ],
)
def test_retryable_defaults(category: ProviderErrorCategory, retryable: bool) -> None:
    assert ProviderError(category).retryable is retryable


def test_retryable_can_be_overridden() -> None:
    error = ProviderError(ProviderErrorCategory.AUTHENTICATION, retryable=True)
    assert error.retryable is True
    assert str(error.category) == "authentication_error"


def test_transient_body_reclassifies_400_as_retryable() -> None:
    # The 9 Router gateway returns HTTP 400 for a transient upstream outage.
    body = (
        '{"error":{"message":"[400]: {\\"error\\":{\\"type\\":\\"server_error\\",'
        '\\"message\\":\\"Upstream request failed: Model is unavailable.\\"}}",'
        '"type":"invalid_request_error","code":"bad_request"}}'
    )
    category = classify_error_response(400, body)
    assert category is ProviderErrorCategory.UNAVAILABLE
    assert ProviderError(category).retryable is True


def test_plain_400_stays_invalid_request() -> None:
    assert (
        classify_error_response(400, '{"error":{"message":"missing model field"}}')
        is ProviderErrorCategory.INVALID_REQUEST
    )


def test_auth_failure_is_never_reclassified() -> None:
    assert (
        classify_error_response(401, "service unavailable") is ProviderErrorCategory.AUTHENTICATION
    )
