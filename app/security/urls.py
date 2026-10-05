"""Outbound URL safety (SSRF protection).

Custom LLM provider endpoints are user-supplied URLs. Before the server ever
fetches one, it must be validated to prevent Server-Side Request Forgery against
internal networks and cloud metadata services.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

from app.exceptions import ValidationError

_ALLOWED_SCHEMES = {"http", "https"}


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        # IPv4-mapped IPv6 addresses inherit the checks above via ``is_private``
        # in modern Python, but we guard the common metadata address explicitly.
        or str(ip) == "169.254.169.254"
    )


def is_safe_outbound_url(url: str, *, allow_private: bool = False) -> bool:
    """Return whether ``url`` is safe for the server to call.

    Best-effort: this resolves the hostname at validation time. A DNS-rebinding
    attack could still return a different address at connect time, so callers
    that own the HTTP transport should also pin/verify the resolved address.
    ``# ponytail: time-of-check DNS guard; add address pinning if the threat model demands``
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return False

    if parts.scheme not in _ALLOWED_SCHEMES:
        return False
    if not parts.hostname:
        return False
    if parts.username or parts.password:
        return False  # credentials in URL are not allowed
    if allow_private:
        return True

    host = parts.hostname
    # Literal IP address?
    try:
        return not _is_blocked_ip(ipaddress.ip_address(host))
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80))
    except socket.gaierror:
        return False

    if not infos:
        return False
    return all(not _is_blocked_ip(ipaddress.ip_address(info[4][0])) for info in infos)


def assert_safe_outbound_url(url: str, *, allow_private: bool = False) -> str:
    """Validate ``url`` or raise :class:`ValidationError`."""
    if not is_safe_outbound_url(url, allow_private=allow_private):
        raise ValidationError("The provided endpoint URL is not allowed.")
    return url
