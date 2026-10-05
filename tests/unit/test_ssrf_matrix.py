"""SSRF hardening matrix for outbound provider URLs.

Covers the address ranges from the Phase 8 audit, including IPv6 private and
link-local ranges, and the DNS-resolution path (via a patched resolver so the
test never depends on real DNS). DNS-rebinding at connect time is documented in
``app/security/urls.py``; the guard here is time-of-check.
"""

from __future__ import annotations

import socket

import pytest
from app.security.urls import is_safe_outbound_url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/v1",
        "http://127.0.0.1:8080/v1",
        "http://localhost:11434/v1",
        "http://[::1]/v1",
        "http://10.0.0.1/v1",
        "http://10.255.255.254/v1",
        "http://172.16.0.1/v1",
        "http://172.31.255.255/v1",
        "http://192.168.0.1/v1",
        "http://192.168.255.255/v1",
        "http://169.254.0.1/v1",
        "http://169.254.169.254/latest/meta-data",
        "http://[fe80::1]/v1",
        "http://[fc00::1]/v1",
        "http://0.0.0.0/v1",
        "http://[::ffff:127.0.0.1]/v1",
    ],
)
def test_private_and_special_ranges_blocked(url: str) -> None:
    assert not is_safe_outbound_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://1.1.1.1/v1",
        "https://8.8.8.8/v1",
        "https://[2606:4700:4700::1111]/v1",
    ],
)
def test_public_literal_ips_allowed(url: str) -> None:
    assert is_safe_outbound_url(url)


@pytest.mark.parametrize("scheme", ["ftp", "file", "gopher", "ws"])
def test_non_http_schemes_blocked(scheme: str) -> None:
    assert not is_safe_outbound_url(f"{scheme}://example.com/x")


def test_credentials_in_url_blocked() -> None:
    assert not is_safe_outbound_url("https://user:secret@1.1.1.1/v1")


def test_hostname_resolving_to_private_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", port))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    assert not is_safe_outbound_url("https://internal.example.com/v1")


def test_hostname_resolving_to_public_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    assert is_safe_outbound_url("https://example.com/v1")


def test_allow_private_bypasses_guard_when_explicit() -> None:
    assert is_safe_outbound_url("http://127.0.0.1:11434/v1", allow_private=True)
    assert is_safe_outbound_url("http://10.0.0.5/v1", allow_private=True)
