"""Provider connection testing with safe, secret-free diagnostics.

Never returns or logs the provider API key. Custom URLs are SSRF-validated
before any request is made.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.exceptions import ConfigurationError
from app.providers.runtime import ProviderRuntime
from app.security.urls import is_safe_outbound_url


class ConnectionTestStatus(StrEnum):
    CONNECTED = "connected"
    AUTHENTICATION_FAILED = "authentication_failed"
    MODEL_UNAVAILABLE = "model_unavailable"
    ENDPOINT_UNREACHABLE = "endpoint_unreachable"
    UNSUPPORTED_PROTOCOL = "unsupported_protocol"
    UNSAFE_URL = "unsafe_url"


@dataclass(frozen=True, slots=True)
class ConnectionTestResult:
    status: ConnectionTestStatus
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status is ConnectionTestStatus.CONNECTED


class ProviderConnectionTester:
    def __init__(self, runtime: ProviderRuntime) -> None:
        self._runtime = runtime

    async def test(
        self,
        *,
        connection_id: str,
        provider_id: str | None = None,
        model_identifier: str | None = None,
        allow_private: bool = False,
    ) -> ConnectionTestResult:
        connection = await self._runtime.connection(connection_id)
        base_url = connection.base_url or ""
        if base_url and not is_safe_outbound_url(base_url, allow_private=allow_private):
            return ConnectionTestResult(
                ConnectionTestStatus.UNSAFE_URL,
                "The endpoint URL is not allowed (internal or unsafe address).",
            )

        try:
            provider = await self._runtime.build(
                connection_id=connection_id,
                provider_id=provider_id,
                model_identifier=model_identifier,
                options={"allow_private": True},
            )
        except ConfigurationError as exc:
            return ConnectionTestResult(ConnectionTestStatus.UNSUPPORTED_PROTOCOL, str(exc))

        try:
            diagnose = getattr(provider, "diagnose", None)
            if diagnose is not None:
                outcome = await diagnose()
                status = ConnectionTestStatus(outcome)
            else:
                connected = await provider.validate_connection()
                status = (
                    ConnectionTestStatus.CONNECTED
                    if connected
                    else ConnectionTestStatus.ENDPOINT_UNREACHABLE
                )
        finally:
            await ProviderRuntime.close(provider)

        messages = {
            ConnectionTestStatus.CONNECTED: "Connected.",
            ConnectionTestStatus.AUTHENTICATION_FAILED: "Authentication failed.",
            ConnectionTestStatus.MODEL_UNAVAILABLE: "Model unavailable.",
            ConnectionTestStatus.ENDPOINT_UNREACHABLE: "Endpoint unreachable.",
        }
        return ConnectionTestResult(status, messages.get(status, "Unknown connection state."))
