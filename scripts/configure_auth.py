"""Configure PocketBase's users collection for OAuth-only sign-in.

Usage::

    uv run python scripts/configure_auth.py

Requires ``POCKETBASE_SERVICE_CREDENTIAL`` (a superuser token or
``identity:password``) and the provider credentials in the environment:

* ``GOOGLE_OAUTH_CLIENT_ID`` / ``GOOGLE_OAUTH_CLIENT_SECRET``
* ``GITHUB_OAUTH_CLIENT_ID`` / ``GITHUB_OAUTH_CLIENT_SECRET``

Register ``<APP_BASE_URL>/auth/oauth2/callback`` as the authorized redirect URI
at Google / the authorization callback URL at GitHub. Idempotent: providers
already configured in PocketBase are kept when the environment leaves them
empty, and only the supplied secrets are overwritten.
"""

from __future__ import annotations

import sys
from typing import Any

import anyio
import httpx
from app.config import Settings, get_settings
from app.repositories.pocketbase import PocketBaseClient
from app.services.service_auth import resolve_service_token

PROVIDERS = ("google", "github")


def _credentials(settings: Settings) -> dict[str, tuple[str, str]]:
    google_secret = settings.google_oauth_client_secret
    github_secret = settings.github_oauth_client_secret
    return {
        "google": (
            settings.google_oauth_client_id,
            google_secret.get_secret_value() if google_secret else "",
        ),
        "github": (
            settings.github_oauth_client_id,
            github_secret.get_secret_value() if github_secret else "",
        ),
    }


def _merge_providers(
    existing: list[dict[str, Any]], credentials: dict[str, tuple[str, str]]
) -> list[dict[str, Any]]:
    """Add or update google/github without dropping other stored settings."""
    providers = [dict(p) for p in existing if str(p.get("name") or "") in PROVIDERS]
    by_name = {str(p.get("name")): p for p in providers}
    for name in PROVIDERS:
        client_id, client_secret = credentials[name]
        if not client_id:
            continue
        provider = by_name.get(name)
        if provider is None:
            if not client_secret:
                continue
            provider = {
                "pkce": None,
                "name": name,
                "clientId": client_id,
                "clientSecret": client_secret,
                "authURL": "",
                "tokenURL": "",
                "userInfoURL": "",
                "displayName": "",
                "extra": {},
            }
            providers.append(provider)
            by_name[name] = provider
        else:
            provider["clientId"] = client_id
            if client_secret:
                provider["clientSecret"] = client_secret
    return providers


async def run() -> int:
    settings = get_settings()
    credential = settings.pocketbase_service_credential
    if credential is None:
        print("POCKETBASE_SERVICE_CREDENTIAL is required.", file=sys.stderr)
        return 1

    client = PocketBaseClient(settings.pocketbase_url)
    base = settings.pocketbase_url.rstrip("/")
    try:
        token = await resolve_service_token(client, credential.get_secret_value())
        if not token:
            print("Could not resolve a PocketBase service token.", file=sys.stderr)
            return 1

        async with httpx.AsyncClient(base_url=base, timeout=20.0) as http:
            headers = {"Authorization": token}
            response = await http.get("/api/collections/users", headers=headers)
            if response.status_code != 200:
                print(
                    f"Could not read the users schema (HTTP {response.status_code}).",
                    file=sys.stderr,
                )
                return 1
            data = response.json()

            oauth2 = dict(data.get("oauth2") or {})
            providers = _merge_providers(oauth2.get("providers") or [], _credentials(settings))
            oauth2["providers"] = providers
            oauth2["enabled"] = bool(providers)

            # Keep nested auth objects intact; only flip the switch.
            flags = {
                "passwordAuth": {**(data.get("passwordAuth") or {}), "enabled": False},
                "otp": {**(data.get("otp") or {}), "enabled": False},
                "mfa": {**(data.get("mfa") or {}), "enabled": False},
                "createRule": '@request.context = "oauth2"',
            }
            patched = await http.patch(
                "/api/collections/users",
                headers=headers,
                json={"oauth2": oauth2, **flags},
            )
            if patched.status_code == 200:
                names = ", ".join(sorted({str(p.get("name")) for p in providers})) or "none"
                print(f"OAuth-only sign-in enabled; providers: {names}")
                print(f"Callback URL: {settings.app_base_url.rstrip('/')}/auth/oauth2/callback")
                return 0

            if "clientSecret" not in patched.text:
                print(
                    f"Could not update the users auth options (HTTP {patched.status_code}): "
                    f"{patched.text[:300]}",
                    file=sys.stderr,
                )
                return 1

            # Older PocketBase cannot merge redacted provider secrets: still
            # enforce OAuth-only sign-in and leave providers untouched.
            fallback = await http.patch(
                "/api/collections/users",
                headers=headers,
                json=flags,
            )
            if fallback.status_code != 200:
                print(
                    f"Could not disable password sign-in (HTTP {fallback.status_code}): "
                    f"{fallback.text[:300]}",
                    file=sys.stderr,
                )
                return 1
            print(
                "WARNING: providers were left unchanged (this PocketBase cannot merge "
                "redacted client secrets). Configure Google/GitHub in the Dashboard, "
                "then re-run.",
                file=sys.stderr,
            )
            return 0
    finally:
        await client.aclose()


def main() -> None:
    raise SystemExit(anyio.run(run))


if __name__ == "__main__":
    main()
