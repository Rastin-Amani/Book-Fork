"""Unit tests for SSRF / outbound URL validation."""

from __future__ import annotations

import pytest
from app.exceptions import ValidationError
from app.security.urls import assert_safe_outbound_url, is_safe_outbound_url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8080/v1",
        "http://localhost:11434/api",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.5/v1",
        "http://192.168.1.1/v1",
        "ftp://example.com/file",
        "file:///etc/passwd",
        "http://user:pass@example.com/v1",
        "",
    ],
)
def test_blocks_unsafe_urls(url: str) -> None:
    assert not is_safe_outbound_url(url)


def test_allows_public_url() -> None:
    # Literal public IP avoids depending on DNS in the test environment.
    assert is_safe_outbound_url("https://1.1.1.1/v1")


def test_private_allowed_when_explicit() -> None:
    assert is_safe_outbound_url("http://127.0.0.1:11434/v1", allow_private=True)


def test_assert_raises_on_unsafe() -> None:
    with pytest.raises(ValidationError):
        assert_safe_outbound_url("http://169.254.169.254/")
