"""The OAuth provider merge must preserve stored secrets and add new providers."""

from __future__ import annotations

from typing import Any

from scripts.configure_auth import _merge_providers


def test_merge_updates_ids_and_keeps_redacted_secrets() -> None:
    existing: list[dict[str, Any]] = [
        {"name": "google", "clientId": "old", "clientSecret": "keep", "pkce": None},
        {"name": "gitlab", "clientId": "other"},
    ]

    merged = _merge_providers(
        existing,
        {"google": ("new", ""), "github": ("gh-id", "gh-secret")},
    )

    by_name = {p["name"]: p for p in merged}
    assert set(by_name) == {"google", "github"}
    assert by_name["google"]["clientId"] == "new"
    assert by_name["google"]["clientSecret"] == "keep"
    assert by_name["github"]["clientSecret"] == "gh-secret"


def test_missing_credentials_leave_providers_untouched() -> None:
    existing: list[dict[str, Any]] = [
        {"name": "github", "clientId": "gh", "clientSecret": "secret"}
    ]

    merged = _merge_providers(existing, {"google": ("", ""), "github": ("", "")})

    assert merged == existing
