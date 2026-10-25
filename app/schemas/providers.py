"""Provider, connection, model, and capability domain records."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field

from app.schemas.base import Record


class ProviderType(StrEnum):
    OPENAI_COMPATIBLE = "openai_compatible"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    OLLAMA = "ollama"
    CUSTOM = "custom"


class AuthType(StrEnum):
    API_KEY = "api_key"
    BEARER = "bearer"
    NONE = "none"
    CUSTOM = "custom"


class BillingMode(StrEnum):
    """Whether a connection is Book Fork-managed or the user's own account."""

    MANAGED = "managed"
    OWN_API = "own_api"


class Provider(Record):
    name: str
    slug: str
    provider_type: ProviderType
    authentication_type: AuthType
    base_url: str | None = None
    enabled: bool = True
    description: str | None = None
    capabilities: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderConnection(Record):
    workspace: str
    provider: str
    name: str
    auth_type: AuthType
    base_url: str | None = None
    enabled: bool = True
    billing_mode: BillingMode = BillingMode.MANAGED
    config: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderCredential(Record):
    """Server-only record; never exposed through a public API rule."""

    connection: str
    encrypted_credential: str
    key_hint: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderModel(Record):
    provider: str
    model_identifier: str
    display_name: str | None = None
    enabled: bool = True
    context_window: int | None = None
    max_output_tokens: int | None = None
    supports_structured_output: bool = False
    supports_vision: bool = False
    supports_temperature: bool = False
    input_cost_per_million_tokens: float | None = None
    output_cost_per_million_tokens: float | None = None
    request_cost: float | None = None
    quality_score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelCapability(Record):
    model: str
    source_language: str
    target_language: str
    supported: bool = True
    preferred: bool = False
    quality_score: float | None = None
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
