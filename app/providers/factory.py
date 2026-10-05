"""Provider adapter factory.

Maps a configured ``provider_type`` to a protocol adapter. Providers are records;
this contains only adapters for supported protocols.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.exceptions import ConfigurationError
from app.providers.base import TranslationProvider
from app.providers.openai_compatible import OpenAICompatibleProvider

_OPENAI_COMPATIBLE = frozenset({"openai_compatible", "ollama", "custom_openai"})


def build_provider(
    *,
    provider_type: str,
    model_identifier: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    options: Mapping[str, Any] | None = None,
) -> TranslationProvider:
    """Construct a provider adapter from configuration."""
    opts = dict(options or {})
    if provider_type in _OPENAI_COMPATIBLE:
        if not base_url:
            raise ConfigurationError("An OpenAI-compatible provider requires a base URL.")
        return OpenAICompatibleProvider(
            base_url=base_url,
            model=model_identifier,
            api_key=api_key,
            auth_scheme=str(opts.get("auth_scheme", "Bearer")),
            auth_header=str(opts.get("auth_header", "Authorization")),
            timeout_seconds=float(opts.get("timeout_seconds", 60.0)),
            supports_structured_output=bool(opts.get("supports_structured_output", True)),
            extra_headers=opts.get("extra_headers"),
        )
    raise ConfigurationError(
        f"Provider protocol {provider_type!r} is not implemented in this deployment."
    )
