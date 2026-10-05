"""Connection testing and SSRF protection for custom provider endpoints."""

from __future__ import annotations

from typing import Any, cast

from app.exceptions import ConfigurationError
from app.providers.base import ProviderRequest, ProviderResponse, ProviderUsage
from app.providers.testing import ConnectionTestStatus, ProviderConnectionTester
from app.schemas.providers import ProviderConnection


class _StubConnection:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url


class _StubProvider:
    name = "stub"
    supports_structured_output = True

    def __init__(self, diagnostic: str | None, connected: bool = True) -> None:
        self._diagnostic = diagnostic
        self._connected = connected
        self.closed = False

    async def diagnose(self) -> str:
        assert self._diagnostic is not None
        return self._diagnostic

    async def validate_connection(self) -> bool:
        return self._connected

    async def translate(self, request: ProviderRequest) -> ProviderResponse:
        return ProviderResponse(usage=ProviderUsage())

    async def estimate_usage(self, request: ProviderRequest) -> ProviderUsage:
        return ProviderUsage(estimated=True)

    async def aclose(self) -> None:
        self.closed = True


class _NoDiagnoseProvider:
    name = "stub"
    supports_structured_output = True

    async def validate_connection(self) -> bool:
        return False

    async def translate(self, request: ProviderRequest) -> ProviderResponse:
        return ProviderResponse(usage=ProviderUsage())

    async def estimate_usage(self, request: ProviderRequest) -> ProviderUsage:
        return ProviderUsage(estimated=True)

    async def aclose(self) -> None:
        return None


class _StubRuntime:
    def __init__(self, connection: _StubConnection, provider: Any) -> None:
        self._connection = connection
        self._provider = provider

    async def connection(self, connection_id: str) -> ProviderConnection:
        return ProviderConnection(
            id=connection_id,
            workspace="w1",
            provider="p1",
            name="c",
            auth_type="api_key",
            base_url=self._connection.base_url,
        )

    async def build(self, **kwargs: Any) -> Any:
        if isinstance(self._provider, Exception):
            raise self._provider
        return self._provider


def _tester(base_url: str, provider: Any) -> ProviderConnectionTester:
    runtime = _StubRuntime(_StubConnection(base_url), provider)
    return ProviderConnectionTester(cast("Any", runtime))


async def test_unsafe_url_is_rejected_before_connecting() -> None:
    result = await _tester("http://127.0.0.1:8080/v1", _StubProvider("connected")).test(
        connection_id="c1"
    )
    assert result.status is ConnectionTestStatus.UNSAFE_URL


async def test_connected() -> None:
    result = await _tester("https://1.1.1.1/v1", _StubProvider("connected")).test(
        connection_id="c1"
    )
    assert result.status is ConnectionTestStatus.CONNECTED
    assert result.ok


async def test_authentication_failed() -> None:
    result = await _tester("https://1.1.1.1/v1", _StubProvider("authentication_failed")).test(
        connection_id="c1"
    )
    assert result.status is ConnectionTestStatus.AUTHENTICATION_FAILED
    assert not result.ok


async def test_endpoint_unreachable_without_diagnose() -> None:
    result = await _tester("https://1.1.1.1/v1", _NoDiagnoseProvider()).test(connection_id="c1")
    assert result.status is ConnectionTestStatus.ENDPOINT_UNREACHABLE


async def test_unsupported_protocol() -> None:
    result = await _tester(
        "https://1.1.1.1/v1",
        ConfigurationError("protocol not implemented"),
    ).test(connection_id="c1")
    assert result.status is ConnectionTestStatus.UNSUPPORTED_PROTOCOL
