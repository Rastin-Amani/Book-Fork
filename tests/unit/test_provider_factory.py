"""Provider adapter factory."""

from __future__ import annotations

import pytest
from app.exceptions import ConfigurationError
from app.providers.factory import build_provider
from app.providers.openai_compatible import OpenAICompatibleProvider


def test_builds_openai_compatible() -> None:
    provider = build_provider(
        provider_type="openai_compatible",
        model_identifier="gpt-x",
        base_url="https://api.example.com/v1",
        api_key="secret",
        options={"timeout_seconds": 5, "supports_structured_output": True},
    )
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.supports_structured_output is True


def test_builds_ollama_as_openai_compatible() -> None:
    provider = build_provider(
        provider_type="ollama",
        model_identifier="llama3",
        base_url="http://localhost:11434/v1",
    )
    assert isinstance(provider, OpenAICompatibleProvider)


def test_missing_base_url_rejected() -> None:
    with pytest.raises(ConfigurationError):
        build_provider(provider_type="openai_compatible", base_url=None)


def test_unknown_provider_rejected() -> None:
    with pytest.raises(ConfigurationError):
        build_provider(provider_type="anthropic", base_url="https://x")
